"""과목별 백엔드 라우팅 solver — 과목마다 다른 LLM 백엔드로 푼다.

측정 근거(2026-06): 로컬 int4(qwen3.5:27b)는 세법 39문항에서 69.2%가 천장이며,
잔존 오답은 지식/검색이 아니라 다단계 계산 실패였다. 같은 RAG+프롬프트로
모델만 클라우드(codex)로 교체하니 로컬이 0/9였던 문항을 8/9 풀었다.
→ 계산 부담이 큰 과목(세법)만 강한 백엔드로 라우팅하면 비용 대비 정확도를 올린다.

설계: 과목→Solver 매핑 + default Solver. solve(q)는 q["subject"]로 분기한다.
RAG 청크는 한 번만 로드해 모든 하위 solver가 공유한다.

설정:
- routes 인자: {"tax": "codex"} 형태(과목→백엔드 이름)
- 또는 환경변수 CPA_LLM_ROUTES="tax:codex,corporate_law:codex"
- default_backend: 매핑에 없는 과목용(CPA_LLM_BACKEND 기본)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from cpa_first.solver.solver import Solver, SolveResult


@dataclass
class RoutingSolver:
    """과목(subject)별로 다른 Solver에 위임한다.

    routes에 없는 과목은 default로 보낸다. mode/model은 벤치마크 호환용 라벨.
    """

    routes: dict[str, Solver]
    default: Solver
    mode: str = "routing"
    model: str = "routing"
    route_labels: dict[str, str] = field(default_factory=dict)

    def solve(self, question: dict[str, Any]) -> SolveResult:
        subject = question.get("subject")
        solver = self.routes.get(subject, self.default)
        return solver.solve(question)


def parse_routes(spec: str | None) -> dict[str, str]:
    """ "tax:codex,corporate_law:codex" → {"tax":"codex","corporate_law":"codex"}."""
    routes: dict[str, str] = {}
    if not spec:
        return routes
    for pair in spec.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise ValueError(f"잘못된 route 형식(과목:백엔드 이어야 함): {pair!r}")
        subject, backend = pair.split(":", 1)
        subject, backend = subject.strip(), backend.strip().lower()
        if subject and backend:
            routes[subject] = backend
    return routes


def create_routing_solver(
    route_backends: dict[str, str] | None = None,
    *,
    default_backend: str | None = None,
    rag_dir: Any = None,
    model: str | None = None,
    calc_scaffold: bool = False,
    rag_top_k: int = 3,
) -> RoutingSolver:
    """과목별 백엔드 라우팅 solver 생성.

    route_backends 미지정 시 CPA_LLM_ROUTES, default_backend 미지정 시 CPA_LLM_BACKEND.
    RAG 청크는 한 번만 로드해 모든 하위 solver가 공유한다(중복 로드 회피).
    """
    route_backends = route_backends or parse_routes(os.environ.get("CPA_LLM_ROUTES"))
    default_backend = (default_backend or os.environ.get("CPA_LLM_BACKEND") or "ollama").lower()

    rag_chunks: list[Any] = []
    if rag_dir is not None:
        from cpa_first.rag import load_chunks

        rag_chunks = load_chunks(rag_dir)

    # 백엔드 이름 → invoke 콜백을 캐시(같은 백엔드 중복 생성 회피).
    from cpa_first.llm import make_invoke

    invoke_cache: dict[str, Any] = {}

    def _solver_for(backend: str) -> Solver:
        if backend not in invoke_cache:
            invoke_cache[backend] = make_invoke(backend, model=model)
        return Solver(
            mode="live",
            model=f"{backend}:{model or 'default'}",
            invoke=invoke_cache[backend],
            rag_chunks=rag_chunks,
            rag_top_k=rag_top_k,
            calc_scaffold=calc_scaffold,
        )

    routes: dict[str, Solver] = {
        subject: _solver_for(backend) for subject, backend in route_backends.items()
    }
    default_solver = _solver_for(default_backend)
    return RoutingSolver(
        routes=routes,
        default=default_solver,
        route_labels={s: b for s, b in route_backends.items()},
    )
