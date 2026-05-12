"""FastAPI 진단 / 처방 / 근거 추적 백엔드.

단일 사용자 가정. 마지막 진단/처방을 `data/runtime/`에 파일로 저장한다.
앱 재시작 후에도 GET /prescription 으로 마지막 처방을 받을 수 있다.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cpa_first.engine import (
    aggregate_user_state,
    diagnose_problem_attempt,
    load_decision_rules,
    load_problem_intelligence,
    load_problem_solution_maps,
    prescribe,
)
from cpa_first.subjects import all_subject_ids


ROOT = Path(__file__).resolve().parents[2]
RULES_DIR = ROOT / "data" / "seeds" / "decision_rules"
PROBLEMS_DIR = ROOT / "data" / "seeds" / "problems"
PROTOTYPE_DIR = ROOT / "prototype"
PROBLEM_MAPS_PATH = PROTOTYPE_DIR / "problem_solution_maps.json"
RUNTIME_DIR = ROOT / "data" / "runtime"
ACTIVE_USER_STATE_PATH = RUNTIME_DIR / "active_user_state.json"
ACTIVE_PRESCRIPTION_PATH = RUNTIME_DIR / "active_prescription.json"
MISTAKE_LOGS_PATH = RUNTIME_DIR / "mistake_logs.jsonl"
ATTEMPT_DIAGNOSES_PATH = RUNTIME_DIR / "attempt_diagnoses.jsonl"

REVIEWABLE_REF_TYPES = {"decision_rule", "problem_intelligence"}
REVIEW_STATUSES_RULE = {"machine_draft", "machine_extracted", "human_reviewed", "approved", "rejected"}
REVIEW_STATUSES_PROBLEM = {"ai_draft", "expert_reviewed", "approved", "rejected"}

# 등록된 과목 id 합집합으로 동적 패턴 생성. 새 과목 추가 시 subjects.py만 수정.
_SUBJECT_PATTERN = "^(" + "|".join(all_subject_ids()) + ")$"


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
    user_id: str = "active-user"
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
    user_id: str = "active-user"
    problem_id: str
    attempt_at: str
    correct: bool
    time_seconds: int = Field(ge=0)
    skipped: bool | None = None
    mistake_categories: list[str] = Field(default_factory=list)
    self_note: str | None = None
    session_id: str | None = None


class AttemptDiagnoseIn(BaseModel):
    attempt_id: str | None = None
    user_id: str = "active-user"
    question_id: str
    selected_choice: int = Field(ge=0)
    time_seconds: int | None = Field(default=None, ge=0)
    time_limit_seconds: int = Field(default=120, ge=1)


class RefreshContext(BaseModel):
    user_id: str = "active-user"
    target_exam: str = "CPA_1"
    days_until_exam: int = Field(ge=0)
    available_hours_per_day: float = Field(ge=0)
    current_stage: str = Field(
        pattern="^(intro|post_lecture|objective_entry|past_exam_rotation|mock_exam|final)$"
    )


class ReviewIn(BaseModel):
    review_status: str
    reviewer: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _user_state_dict(req: DiagnoseRequest) -> dict[str, Any]:
    state: dict[str, Any] = {
        "user_id": req.user_id,
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


def _persist(user_state: dict, prescription: dict) -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    with ACTIVE_USER_STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(user_state, f, ensure_ascii=False, indent=2)
    with ACTIVE_PRESCRIPTION_PATH.open("w", encoding="utf-8") as f:
        json.dump(prescription, f, ensure_ascii=False, indent=2)


def _load_active() -> tuple[dict, dict] | None:
    if not (ACTIVE_USER_STATE_PATH.exists() and ACTIVE_PRESCRIPTION_PATH.exists()):
        return None
    with ACTIVE_USER_STATE_PATH.open("r", encoding="utf-8") as f:
        us = json.load(f)
    with ACTIVE_PRESCRIPTION_PATH.open("r", encoding="utf-8") as f:
        rx = json.load(f)
    return us, rx


def create_app(
    *,
    rules_dir: Path = RULES_DIR,
    problems_dir: Path = PROBLEMS_DIR,
    problem_maps_path: Path = PROBLEM_MAPS_PATH,
) -> FastAPI:
    """앱 팩토리. 테스트에서는 별도 디렉터리를 주입할 수 있다."""
    app = FastAPI(title="CPA First", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    # 시작 시 한 번 로드. 시드 갱신은 재시작으로 반영.
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

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "decision_rules": len(rules),
            "problems": len(problems),
            "problem_solution_maps": len(problem_solution_maps),
        }

    @app.post("/diagnose", response_model=DiagnoseResponse)
    def diagnose(req: DiagnoseRequest) -> DiagnoseResponse:
        user_state = _user_state_dict(req)
        rx = prescribe(
            user_state,
            rules,
            generated_at=_now_iso(),
            problem_intel=problems,
        )
        _persist(user_state, rx)
        return DiagnoseResponse(user_state=user_state, prescription=rx)

    @app.get("/prescription", response_model=DiagnoseResponse)
    def get_prescription() -> DiagnoseResponse:
        active = _load_active()
        if active is None:
            raise HTTPException(
                status_code=404,
                detail="No active prescription. POST /diagnose first.",
            )
        user_state, rx = active
        return DiagnoseResponse(user_state=user_state, prescription=rx)

    @app.get("/problems/{problem_id}")
    def get_problem(problem_id: str) -> dict[str, Any]:
        problem = problems_by_id.get(problem_id)
        if problem is None:
            raise HTTPException(status_code=404, detail=f"problem not found: {problem_id}")
        return problem

    @app.get("/evidence/{ref_type}/{ref_id}")
    def get_evidence(ref_type: str, ref_id: str) -> dict[str, Any]:
        if ref_type == "decision_rule":
            rule = rules_by_key.get(ref_id)
            if rule is None:
                raise HTTPException(status_code=404, detail=f"rule not found: {ref_id}")
            return {"ref_type": ref_type, "ref_id": ref_id, "data": rule}

        if ref_type == "problem_intelligence":
            problem = problems_by_id.get(ref_id)
            if problem is None:
                raise HTTPException(status_code=404, detail=f"problem not found: {ref_id}")
            return {"ref_type": ref_type, "ref_id": ref_id, "data": problem}

        if ref_type == "problem_solution_map":
            problem_map = problem_maps_by_id.get(ref_id)
            if problem_map is None:
                raise HTTPException(status_code=404, detail=f"problem_solution_map not found: {ref_id}")
            return {"ref_type": ref_type, "ref_id": ref_id, "data": problem_map}

        if ref_type == "solution_path":
            path = solution_paths_by_id.get(ref_id)
            if path is None:
                raise HTTPException(status_code=404, detail=f"solution_path not found: {ref_id}")
            return {"ref_type": ref_type, "ref_id": ref_id, "data": path}

        if ref_type == "user_state":
            active = _load_active()
            if active is None or active[0].get("user_id") != ref_id:
                raise HTTPException(status_code=404, detail=f"user_state not found: {ref_id}")
            return {"ref_type": ref_type, "ref_id": ref_id, "data": active[0]}

        # success_case, extracted_signal 은 M4에서 06번 SQLite 연결 후 지원
        raise HTTPException(
            status_code=501,
            detail=f"ref_type '{ref_type}' resolver not implemented yet",
        )

    # ----- M5: MistakeLog + 자동 user_state -----

    def _read_logs() -> list[dict]:
        if not MISTAKE_LOGS_PATH.exists():
            return []
        out: list[dict] = []
        with MISTAKE_LOGS_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    @app.post("/logs")
    def add_log(log: MistakeLogIn) -> dict[str, Any]:
        if log.problem_id not in problems_by_id:
            raise HTTPException(
                status_code=400, detail=f"unknown problem_id: {log.problem_id}"
            )
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        with MISTAKE_LOGS_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(log.model_dump(), ensure_ascii=False) + "\n")
        return {"status": "ok", "log_count": len(_read_logs())}

    @app.get("/logs")
    def list_logs() -> dict[str, Any]:
        logs = _read_logs()
        return {"count": len(logs), "logs": logs}

    @app.delete("/logs")
    def clear_logs() -> dict[str, Any]:
        if MISTAKE_LOGS_PATH.exists():
            MISTAKE_LOGS_PATH.unlink()
        return {"status": "ok", "log_count": 0}

    # ----- M8: 풀이맵 기반 응시 진단 -----

    def _read_attempt_diagnoses() -> list[dict]:
        if not ATTEMPT_DIAGNOSES_PATH.exists():
            return []
        out: list[dict] = []
        with ATTEMPT_DIAGNOSES_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    @app.post("/attempts/diagnose")
    def diagnose_attempt(req: AttemptDiagnoseIn) -> dict[str, Any]:
        problem_map = problem_maps_by_id.get(req.question_id)
        if problem_map is None:
            raise HTTPException(
                status_code=404,
                detail=f"problem_solution_map not found: {req.question_id}",
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

        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        attempt_id = req.attempt_id or f"attempt-{_now_iso()}-{req.question_id}"
        record = {
            "attempt_id": attempt_id,
            "user_id": req.user_id,
            "question_id": req.question_id,
            "selected_choice": req.selected_choice,
            "time_seconds": req.time_seconds,
            "time_limit_seconds": req.time_limit_seconds,
            "created_at": _now_iso(),
            "diagnosis": diagnosis,
        }
        with ATTEMPT_DIAGNOSES_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return {"status": "ok", "attempt": record, "diagnosis": diagnosis}

    @app.get("/attempts")
    def list_attempts() -> dict[str, Any]:
        attempts = _read_attempt_diagnoses()
        return {"count": len(attempts), "attempts": attempts}

    @app.delete("/attempts")
    def clear_attempts() -> dict[str, Any]:
        if ATTEMPT_DIAGNOSES_PATH.exists():
            ATTEMPT_DIAGNOSES_PATH.unlink()
        return {"status": "ok", "count": 0}

    @app.post("/user-state/refresh", response_model=DiagnoseResponse)
    def refresh_state(ctx: RefreshContext) -> DiagnoseResponse:
        logs = _read_logs()
        if not logs:
            raise HTTPException(
                status_code=400,
                detail="누적된 풀이 로그가 없습니다. 먼저 POST /logs로 입력하세요.",
            )
        user_state = aggregate_user_state(
            logs,
            problems,
            user_id=ctx.user_id,
            target_exam=ctx.target_exam,
            days_until_exam=ctx.days_until_exam,
            available_hours_per_day=ctx.available_hours_per_day,
            current_stage=ctx.current_stage,
        )
        rx = prescribe(
            user_state,
            rules,
            generated_at=_now_iso(),
            problem_intel=problems,
        )
        _persist(user_state, rx)
        return DiagnoseResponse(user_state=user_state, prescription=rx)

    # ----- M4: 검수 워크플로우 -----

    @app.post("/review/{ref_type}/{ref_id}")
    def update_review(ref_type: str, ref_id: str, payload: ReviewIn) -> dict[str, Any]:
        if ref_type not in REVIEWABLE_REF_TYPES:
            raise HTTPException(
                status_code=400, detail=f"검수 불가 ref_type: {ref_type}"
            )

        if ref_type == "decision_rule":
            allowed = REVIEW_STATUSES_RULE
            path = rules_dir / f"{ref_id}.decision_rule.json"
            target_cache = rules_by_key
        else:
            allowed = REVIEW_STATUSES_PROBLEM
            path = problems_dir / f"{ref_id}.problem_intelligence.json"
            target_cache = problems_by_id

        if payload.review_status not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"{ref_type}의 review_status는 {sorted(allowed)} 중 하나여야 함",
            )
        if not path.exists():
            raise HTTPException(
                status_code=404, detail=f"{ref_type} not found: {ref_id}"
            )

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        previous = data.get("review_status")
        data["review_status"] = payload.review_status
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")

        # 메모리 캐시 동기화
        target_cache[ref_id] = data

        return {
            "ref_type": ref_type,
            "ref_id": ref_id,
            "previous_status": previous,
            "review_status": payload.review_status,
            "reviewer": payload.reviewer,
        }

    # 정적 프론트엔드. API 라우트와 충돌하지 않도록 마지막에 마운트.
    if PROTOTYPE_DIR.exists():
        app.mount("/", StaticFiles(directory=PROTOTYPE_DIR, html=True), name="ui")

    return app


app = create_app()


def cli() -> int:
    parser = argparse.ArgumentParser(description="CPA First API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
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
