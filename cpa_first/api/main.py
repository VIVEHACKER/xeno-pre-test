"""FastAPI 진단 / 처방 / 근거 추적 백엔드 — 다중 사용자 · Postgres.

per-user 상태는 전부 DB(SQLAlchemy). user_id는 access 토큰(JWT) subject에서만 주입 →
요청 바디에 user_id 없음(IDOR 차단). KB(시드)는 번들 읽기전용으로 시작 시 메모리 로드.
review_status는 시드 파일을 쓰지 않고 review_overrides DB row로 오버레이.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy.orm import Session

from cpa_first.auth import auth_router, get_current_user, require_admin
from cpa_first.config import Settings, get_settings
from cpa_first.db import repositories as repo
from cpa_first.db.models import User
from cpa_first.db.session import Database, get_db
from cpa_first.engine import (
    aggregate_user_state,
    diagnose_problem_attempt,
    load_decision_rules,
    load_problem_intelligence,
    load_problem_solution_maps,
    prescribe,
)
from cpa_first.logging_config import configure_logging, get_logger
from cpa_first.rag import TermIndex, load_chunks
from cpa_first.ratelimit import limiter
from cpa_first.subjects import all_subject_ids

logger = get_logger("cpa_first.api")


def _seed_root(settings: Settings) -> Path:
    if settings.seed_dir:
        return Path(settings.seed_dir)
    return Path(__file__).resolve().parents[2]


ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE_DIR = ROOT / "prototype"

REVIEWABLE_REF_TYPES = {"decision_rule", "problem_intelligence"}
REVIEW_STATUSES_RULE = {
    "machine_draft",
    "machine_extracted",
    "human_reviewed",
    "approved",
    "rejected",
}
REVIEW_STATUSES_PROBLEM = {"ai_draft", "expert_reviewed", "approved", "rejected"}
KB_EVIDENCE_TYPES = {
    "decision_rule",
    "problem_intelligence",
    "problem_solution_map",
    "solution_path",
}

# ref_id 경로 주입/순회 방지 (security: /review 경로 traversal 차단).
_REF_ID_PATTERN = "^[A-Za-z0-9_.-]+$"
_REF_ID_RE = re.compile(_REF_ID_PATTERN)

_SUBJECT_PATTERN = "^(" + "|".join(all_subject_ids()) + ")$"


# ─────────────────────────── Pydantic 모델 (user_id는 바디에서 제거) ───────────────────────────


class ConceptMastery(BaseModel):
    concept: str
    mastery: float = Field(ge=0, le=1)


class SubjectStateIn(BaseModel):
    subject: str = Field(pattern=_SUBJECT_PATTERN)
    accuracy: float = Field(ge=0, le=1)
    time_overrun_rate: float = Field(ge=0, le=1)
    risk_tags: list[str] = Field(default_factory=list)
    concept_mastery: list[ConceptMastery] | None = None


class DiagnoseRequest(BaseModel):
    target_exam: str = "CPA_1"
    days_until_exam: int = Field(ge=0)
    available_hours_per_day: float = Field(ge=0)
    current_stage: str = Field(
        pattern="^(intro|post_lecture|objective_entry|past_exam_rotation|mock_exam|final)$"
    )
    subject_states: list[SubjectStateIn]


class DiagnoseResponse(BaseModel):
    user_state: dict[str, Any]
    prescription: dict[str, Any]


class MistakeLogIn(BaseModel):
    log_id: str
    problem_id: str
    attempt_at: str
    correct: bool
    time_seconds: int = Field(ge=0)
    skipped: bool | None = None
    mistake_categories: list[str] = Field(default_factory=list)
    self_note: str | None = Field(default=None, max_length=2000)
    session_id: str | None = None


class AttemptDiagnoseIn(BaseModel):
    # attempt_id는 받지 않는다 — 서버가 생성(클라이언트 위조/PK 충돌 오라클 차단).
    question_id: str
    selected_choice: int = Field(ge=0)
    time_seconds: int | None = Field(default=None, ge=0)
    time_limit_seconds: int = Field(default=120, ge=1)


class RefreshContext(BaseModel):
    target_exam: str = "CPA_1"
    days_until_exam: int = Field(ge=0)
    available_hours_per_day: float = Field(ge=0)
    current_stage: str | None = Field(
        default=None,
        pattern="^(intro|post_lecture|objective_entry|past_exam_rotation|mock_exam|final)$",
    )


class ReviewIn(BaseModel):
    review_status: str
    reviewer: str | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _user_state_from_request(req: DiagnoseRequest, user: User) -> dict[str, Any]:
    state: dict[str, Any] = {
        "user_id": str(user.id),
        "target_exam": req.target_exam,
        "days_until_exam": req.days_until_exam,
        "available_hours_per_day": req.available_hours_per_day,
        "current_stage": req.current_stage,
        "subject_states": [],
    }
    for s in req.subject_states:
        item: dict[str, Any] = {
            "subject": s.subject,
            "accuracy": s.accuracy,
            "time_overrun_rate": s.time_overrun_rate,
            "risk_tags": list(s.risk_tags),
        }
        if s.concept_mastery is not None:
            item["concept_mastery"] = [
                {"concept": cm.concept, "mastery": cm.mastery} for cm in s.concept_mastery
            ]
        state["subject_states"].append(item)
    return state


def _state_row_to_dict(row: Any, user: User) -> dict[str, Any]:
    return {
        "user_id": str(user.id),
        "target_exam": row.target_exam,
        "days_until_exam": row.days_until_exam,
        "available_hours_per_day": row.available_hours_per_day,
        "current_stage": row.current_stage,
        "subject_states": row.subject_states or [],
    }


def _load_terms_full(terms_dir: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(terms_dir.glob("*.term.json")):
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        out[data["term_id"]] = data
    return out


def _load_tutorials_meta(tutorials_path: Path) -> dict[str, dict]:
    if not tutorials_path.exists():
        return {}
    with tutorials_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return {
        t["tutorial_id"]: {
            "tutorial_id": t["tutorial_id"],
            "title": t.get("title", ""),
            "subject_name": t.get("subject_name", ""),
        }
        for t in data.get("tutorials", [])
    }


def _error_response(status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=body)


_STATUS_CODE_MAP = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    501: "NOT_IMPLEMENTED",
}


def create_app(
    *,
    settings: Settings | None = None,
    database: Database | None = None,
    seed_dir: Path | None = None,
    prototype_dir: Path = PROTOTYPE_DIR,
) -> FastAPI:
    """앱 팩토리. 테스트는 settings/database/seed 디렉터리를 주입할 수 있다."""
    settings = settings or get_settings()
    configure_logging(settings)

    seed_base = seed_dir or _seed_root(settings)
    rules_dir = seed_base / "data" / "seeds" / "decision_rules"
    problems_dir = seed_base / "data" / "seeds" / "problems"
    terms_dir = seed_base / "data" / "seeds" / "terms"
    edges_path = seed_base / "data" / "seeds" / "term_graph" / "edges.jsonl"
    rag_dir = seed_base / "data" / "seeds" / "rag"
    tutorials_path = seed_base / "data" / "seeds" / "subject_tutorials.json"
    problem_maps_path = prototype_dir / "problem_solution_maps.json"

    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("startup", environment=settings.environment, db_ok=app.state.db.healthcheck())
        try:
            yield
        finally:
            app.state.db.dispose()
            logger.info("shutdown")

    app = FastAPI(title="CPA First", version="0.2.0", lifespan=lifespan)

    # DB: 주입 없으면 settings로 생성. SQLite(dev/test)는 metadata로 스키마 생성.
    db = database or Database(settings)
    if settings.is_sqlite:
        db.create_all()
    app.state.db = db
    app.state.settings = settings

    # ── 레이트 리미터 ──
    app.state.limiter = limiter
    limiter.enabled = settings.rate_limit_enabled

    # ── 미들웨어 (마지막 add가 outermost) ──
    app.add_middleware(SlowAPIMiddleware)

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        request.state.request_id = request_id
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("unhandled_exception", method=request.method, path=request.url.path)
            structlog.contextvars.clear_contextvars()
            raise
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Request-Id"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if settings.is_prod:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
            )
        logger.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        structlog.contextvars.clear_contextvars()
        return response

    cors_origins = settings.cors_origin_list
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-Id"],
        allow_credentials=bool(cors_origins),
    )

    # ── 예외 핸들러: 통일 {error:{code,message,details?}} ──
    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return _error_response(429, "RATE_LIMITED", f"rate limit exceeded: {exc.detail}")

    @app.exception_handler(HTTPException)
    async def _http_exc_handler(request: Request, exc: HTTPException) -> JSONResponse:
        code = _STATUS_CODE_MAP.get(exc.status_code, "ERROR")
        resp = _error_response(exc.status_code, code, str(exc.detail))
        if exc.headers:
            for k, v in exc.headers.items():
                resp.headers[k] = v
        return resp

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return _error_response(422, "VALIDATION_ERROR", "request validation failed", details)

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception("internal_error", path=request.url.path, request_id=request_id)
        return _error_response(500, "INTERNAL", "internal server error", {"request_id": request_id})

    # ── KB(시드) 로드: 시작 시 1회, 읽기 전용 ──
    rules = load_decision_rules(rules_dir)
    problems = load_problem_intelligence(problems_dir)
    problem_solution_maps = (
        load_problem_solution_maps(problem_maps_path) if problem_maps_path.exists() else []
    )
    problems_by_id = {p["problem_id"]: p for p in problems}
    problem_maps_by_id = {p["question_id"]: p for p in problem_solution_maps}
    solution_paths_by_id = {
        path["path_id"]: path
        for problem in problem_solution_maps
        for path in problem.get("solution_paths", [])
    }
    rules_by_key = {r["rule_key"]: r for r in rules}

    terms_full = _load_terms_full(terms_dir) if terms_dir.exists() else {}
    term_index = (
        TermIndex.from_paths(terms_dir, edges_path)
        if terms_dir.exists() and edges_path.exists()
        else TermIndex(terms=[], edges=[])
    )
    chunks_by_id = {c.chunk_id: c for c in (load_chunks(rag_dir) if rag_dir.exists() else [])}
    tutorials_meta = _load_tutorials_meta(tutorials_path)

    def _with_review_override(db_session: Session, ref_type: str, ref_id: str, data: dict) -> dict:
        """시드 데이터에 DB override를 얹어 effective review_status 반영 (원본 캐시 불변)."""
        override = repo.get_review_override(db_session, ref_type, ref_id)
        if override is None:
            return data
        return {**data, "review_status": override.review_status}

    # ───────────────────────── Health ─────────────────────────

    @app.get("/livez", include_in_schema=False)
    def livez() -> dict[str, str]:
        return {"status": "alive"}

    @app.get("/readyz", include_in_schema=False)
    def readyz() -> JSONResponse:
        db_ok = app.state.db.healthcheck()
        payload = {
            "status": "ready" if db_ok else "not_ready",
            "db": db_ok,
            "decision_rules": len(rules),
            "problems": len(problems),
            "problem_solution_maps": len(problem_solution_maps),
            "terms": len(terms_full),
            "term_edges": len(term_index.edges),
        }
        return JSONResponse(status_code=200 if db_ok else 503, content=payload)

    @app.get("/health")
    def health() -> dict[str, Any]:
        """하위호환 + 정보용. 카운트 + DB 상태."""
        return {
            "status": "ok",
            "db": app.state.db.healthcheck(),
            "decision_rules": len(rules),
            "problems": len(problems),
            "problem_solution_maps": len(problem_solution_maps),
            "terms": len(terms_full),
            "term_edges": len(term_index.edges),
        }

    # ───────────────────────── 용어 지식 그래프 (PUBLIC) ─────────────────────────

    @app.get("/terms/search")
    def search_terms(q: str = "", limit: int = 20) -> dict[str, Any]:
        query = q.strip()
        if not query:
            return {"query": q, "results": []}
        matches: list[dict] = []
        for term in terms_full.values():
            forms = [term["name_ko"], *(term.get("aliases") or [])]
            if any(query in f for f in forms if len(f) >= 1):
                matches.append(
                    {
                        "term_id": term["term_id"],
                        "name_ko": term["name_ko"],
                        "name_en": term.get("name_en"),
                        "subject": term["subject"],
                        "unit": term.get("unit"),
                        "difficulty": term["difficulty"],
                    }
                )
        matches.sort(key=lambda m: (0 if m["name_ko"].startswith(query) else 1, m["term_id"]))
        return {"query": q, "results": matches[: max(1, limit)]}

    def _resolve_term_brief(term_id: str) -> dict[str, Any] | None:
        term = terms_full.get(term_id)
        if term is None:
            return {"term_id": term_id, "name_ko": None, "in_seed": False}
        return {
            "term_id": term_id,
            "name_ko": term["name_ko"],
            "subject": term["subject"],
            "in_seed": True,
        }

    @app.get("/terms/{term_id}")
    def get_term(term_id: str) -> dict[str, Any]:
        term = terms_full.get(term_id)
        if term is None:
            raise HTTPException(status_code=404, detail=f"term not found: {term_id}")

        related_chunks: list[dict] = []
        related_problems: list[dict] = []
        related_tutorials: list[dict] = []
        prerequisite_resolved: list[dict] = []

        for edge in term_index.edges:
            if edge.from_term != term_id:
                continue
            if edge.to_kind == "rag_chunk" and edge.relation == "defined_in":
                chunk = chunks_by_id.get(edge.to_id)
                if chunk is not None:
                    related_chunks.append(
                        {
                            "chunk_id": chunk.chunk_id,
                            "title": chunk.title,
                            "subject": chunk.subject,
                            "weight": edge.weight,
                        }
                    )
            elif edge.to_kind == "problem" and edge.relation == "tested_in":
                problem = problems_by_id.get(edge.to_id)
                if problem is not None:
                    related_problems.append(
                        {
                            "problem_id": problem["problem_id"],
                            "subject": problem["subject"],
                            "unit": problem.get("unit"),
                            "weight": edge.weight,
                        }
                    )
            elif edge.to_kind == "tutorial" and edge.relation == "explained_in":
                tut = tutorials_meta.get(edge.to_id)
                if tut is not None:
                    related_tutorials.append({**tut, "weight": edge.weight})

        confusable_resolved: list[dict] = []
        for pair in term.get("confusable_with") or []:
            brief = _resolve_term_brief(pair["term_id"])
            if brief:
                confusable_resolved.append({**brief, "reason": pair["reason"]})

        for pre_id in term.get("prerequisite_terms") or []:
            brief = _resolve_term_brief(pre_id)
            if brief:
                prerequisite_resolved.append(brief)

        return {
            "term": term,
            "related": {
                "chunks": sorted(related_chunks, key=lambda c: (-c["weight"], c["chunk_id"])),
                "problems": sorted(related_problems, key=lambda p: (-p["weight"], p["problem_id"])),
                "tutorials": sorted(
                    related_tutorials, key=lambda t: (-t["weight"], t["tutorial_id"])
                ),
                "confusable_terms": confusable_resolved,
                "prerequisite_terms": prerequisite_resolved,
            },
        }

    # ───────────────────────── 진단 / 처방 (AUTH + per-user) ─────────────────────────

    @app.post("/diagnose", response_model=DiagnoseResponse)
    def diagnose(
        req: DiagnoseRequest,
        user: User = Depends(get_current_user),
        db_session: Session = Depends(get_db),
    ) -> DiagnoseResponse:
        user_state = _user_state_from_request(req, user)
        rx = prescribe(user_state, rules, generated_at=_now_iso(), problem_intel=problems)
        repo.upsert_user_state(db_session, user_id=user.id, state=user_state)
        repo.save_prescription(db_session, user_id=user.id, prescription=rx)
        db_session.commit()
        return DiagnoseResponse(user_state=user_state, prescription=rx)

    @app.get("/prescription", response_model=DiagnoseResponse)
    def get_prescription(
        user: User = Depends(get_current_user),
        db_session: Session = Depends(get_db),
    ) -> DiagnoseResponse:
        rx = repo.get_active_prescription(db_session, user.id)
        state_row = repo.get_user_state(db_session, user.id)
        if rx is None or state_row is None:
            raise HTTPException(
                status_code=404, detail="No active prescription. POST /diagnose first."
            )
        return DiagnoseResponse(
            user_state=_state_row_to_dict(state_row, user), prescription=rx.payload
        )

    @app.get("/problems/{problem_id}")
    def get_problem(problem_id: str, db_session: Session = Depends(get_db)) -> dict[str, Any]:
        problem = problems_by_id.get(problem_id)
        if problem is None:
            raise HTTPException(status_code=404, detail=f"problem not found: {problem_id}")
        return _with_review_override(db_session, "problem_intelligence", problem_id, problem)

    # 전용 라우트가 generic /evidence/{ref_type}/{ref_id}보다 먼저 선언되어야 우선 매칭됨.
    @app.get("/evidence/user_state/{ref_id}")
    def get_user_state_evidence(
        ref_id: str,
        user: User = Depends(get_current_user),
        db_session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        if ref_id != str(user.id):
            raise HTTPException(status_code=403, detail="cannot access another user's state")
        state_row = repo.get_user_state(db_session, user.id)
        if state_row is None:
            raise HTTPException(status_code=404, detail=f"user_state not found: {ref_id}")
        return {
            "ref_type": "user_state",
            "ref_id": ref_id,
            "data": _state_row_to_dict(state_row, user),
        }

    @app.get("/evidence/{ref_type}/{ref_id}")
    def get_evidence(
        ref_type: str,
        ref_id: str,
        db_session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        if ref_type == "decision_rule":
            rule = rules_by_key.get(ref_id)
            if rule is None:
                raise HTTPException(status_code=404, detail=f"rule not found: {ref_id}")
            return {
                "ref_type": ref_type,
                "ref_id": ref_id,
                "data": _with_review_override(db_session, ref_type, ref_id, rule),
            }

        if ref_type == "problem_intelligence":
            problem = problems_by_id.get(ref_id)
            if problem is None:
                raise HTTPException(status_code=404, detail=f"problem not found: {ref_id}")
            return {
                "ref_type": ref_type,
                "ref_id": ref_id,
                "data": _with_review_override(db_session, ref_type, ref_id, problem),
            }

        if ref_type == "problem_solution_map":
            problem_map = problem_maps_by_id.get(ref_id)
            if problem_map is None:
                raise HTTPException(
                    status_code=404, detail=f"problem_solution_map not found: {ref_id}"
                )
            return {"ref_type": ref_type, "ref_id": ref_id, "data": problem_map}

        if ref_type == "solution_path":
            path = solution_paths_by_id.get(ref_id)
            if path is None:
                raise HTTPException(status_code=404, detail=f"solution_path not found: {ref_id}")
            return {"ref_type": ref_type, "ref_id": ref_id, "data": path}

        # user_state는 위의 전용 라우트(/evidence/user_state/{ref_id})가 처리.
        raise HTTPException(
            status_code=501, detail=f"ref_type '{ref_type}' resolver not implemented yet"
        )

    # ───────────────────────── MistakeLog (AUTH + per-user) ─────────────────────────

    @app.post("/logs")
    def add_log(
        log: MistakeLogIn,
        user: User = Depends(get_current_user),
        db_session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        if log.problem_id not in problems_by_id:
            raise HTTPException(status_code=400, detail=f"unknown problem_id: {log.problem_id}")
        repo.add_mistake_log(db_session, user_id=user.id, log=log.model_dump())
        db_session.commit()
        return {"status": "ok", "log_count": repo.count_mistake_logs(db_session, user.id)}

    @app.get("/logs")
    def list_logs(
        user: User = Depends(get_current_user),
        db_session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        logs = repo.list_mistake_logs(db_session, user.id)
        return {"count": len(logs), "logs": logs}

    @app.delete("/logs")
    def clear_logs(
        user: User = Depends(get_current_user),
        db_session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        repo.delete_mistake_logs(db_session, user.id)
        db_session.commit()
        return {"status": "ok", "log_count": 0}

    # ───────────────────────── 응시 진단 (AUTH + per-user) ─────────────────────────

    @app.post("/attempts/diagnose")
    def diagnose_attempt(
        req: AttemptDiagnoseIn,
        user: User = Depends(get_current_user),
        db_session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        problem_map = problem_maps_by_id.get(req.question_id)
        if problem_map is None:
            raise HTTPException(
                status_code=404, detail=f"problem_solution_map not found: {req.question_id}"
            )
        try:
            diagnosis = diagnose_problem_attempt(
                problem_map,
                selected_choice=req.selected_choice,
                time_seconds=req.time_seconds,
                time_limit_seconds=req.time_limit_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        record = repo.add_attempt_diagnosis(
            db_session,
            user_id=user.id,
            question_id=req.question_id,
            selected_choice=req.selected_choice,
            time_seconds=req.time_seconds,
            time_limit_seconds=req.time_limit_seconds,
            diagnosis=diagnosis,
        )
        db_session.commit()
        return {"status": "ok", "attempt": record, "diagnosis": diagnosis}

    @app.get("/attempts")
    def list_attempts(
        user: User = Depends(get_current_user),
        db_session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        attempts = repo.list_attempt_diagnoses(db_session, user.id)
        return {"count": len(attempts), "attempts": attempts}

    @app.delete("/attempts")
    def clear_attempts(
        user: User = Depends(get_current_user),
        db_session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        repo.delete_attempt_diagnoses(db_session, user.id)
        db_session.commit()
        return {"status": "ok", "count": 0}

    @app.post("/user-state/refresh", response_model=DiagnoseResponse)
    def refresh_state(
        ctx: RefreshContext,
        user: User = Depends(get_current_user),
        db_session: Session = Depends(get_db),
    ) -> DiagnoseResponse:
        logs = repo.list_mistake_logs(db_session, user.id)
        if not logs:
            raise HTTPException(
                status_code=400,
                detail="누적된 풀이 로그가 없습니다. 먼저 POST /logs로 입력하세요.",
            )
        user_state = aggregate_user_state(
            logs,
            problems,
            user_id=str(user.id),
            target_exam=ctx.target_exam,
            days_until_exam=ctx.days_until_exam,
            available_hours_per_day=ctx.available_hours_per_day,
            current_stage=ctx.current_stage,
        )
        rx = prescribe(user_state, rules, generated_at=_now_iso(), problem_intel=problems)
        repo.upsert_user_state(db_session, user_id=user.id, state=user_state)
        repo.save_prescription(db_session, user_id=user.id, prescription=rx)
        db_session.commit()
        return DiagnoseResponse(user_state=user_state, prescription=rx)

    # ───────────────────────── 검수 워크플로우 (ADMIN only) ─────────────────────────

    @app.post("/review/{ref_type}/{ref_id}")
    def update_review(
        ref_type: str,
        ref_id: str,
        payload: ReviewIn,
        _admin: User = Depends(require_admin),
        db_session: Session = Depends(get_db),
    ) -> dict[str, Any]:
        # ref_id 검증 (path traversal 차단).
        if not _REF_ID_RE.match(ref_id):
            raise HTTPException(status_code=422, detail="invalid ref_id format")
        if ref_type not in REVIEWABLE_REF_TYPES:
            raise HTTPException(status_code=400, detail=f"검수 불가 ref_type: {ref_type}")

        if ref_type == "decision_rule":
            allowed = REVIEW_STATUSES_RULE
            exists = ref_id in rules_by_key
        else:
            allowed = REVIEW_STATUSES_PROBLEM
            exists = ref_id in problems_by_id

        if payload.review_status not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"{ref_type}의 review_status는 {sorted(allowed)} 중 하나여야 함",
            )
        if not exists:
            raise HTTPException(status_code=404, detail=f"{ref_type} not found: {ref_id}")

        previous, _row = repo.upsert_review_override(
            db_session,
            ref_type=ref_type,
            ref_id=ref_id,
            review_status=payload.review_status,
            reviewer=payload.reviewer,
        )
        db_session.commit()
        return {
            "ref_type": ref_type,
            "ref_id": ref_id,
            "previous_status": previous,
            "review_status": payload.review_status,
            "reviewer": payload.reviewer,
        }

    # ── 인증 라우터 ──
    app.include_router(auth_router)

    # ── 관측성: /metrics ──
    if settings.metrics_enabled:
        try:
            from prometheus_fastapi_instrumentator import Instrumentator

            Instrumentator().instrument(app).expose(
                app, endpoint="/metrics", include_in_schema=False
            )
        except Exception:  # 관측성 미설치 시 앱은 정상 기동
            logger.warning("metrics_unavailable")

    # 정적 프론트엔드. API 라우트와 충돌하지 않도록 마지막에 마운트.
    if prototype_dir.exists():
        app.mount("/", StaticFiles(directory=prototype_dir, html=True), name="ui")

    return app


app = create_app()


def cli() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="CPA First API server")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "cpa_first.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
