"""교차-모델 앙상블 solver — 여러 백엔드로 풀어 다수결 + 합의 신뢰도.

측정 근거(2026-06, KMMLU 150문항): 서로 다른 모델 계열(Claude·codex/GPT)이 **합의**하면
비-Law 과목에서 ~98% 정답 → 자동 신뢰 가능. 불일치는 우선순위(강한 백엔드 먼저)로 tie-break.
agreement를 confidence로 노출해, 앱이 저신뢰(불일치) 문항을 인간검토/RAG로 라우팅하게 한다.

한계(정직): Law(상법)는 모델 간 오류가 상관되어 합의해도 틀릴 수 있음(앙상블로 못 고침).
→ Law는 합의 confidence가 높아도 별도 권위 RAG가 필요. (per-backend 답을 tool_calls에 남겨 감사 가능)
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from cpa_first.solver.solver import Solver, SolveResult


@dataclass
class EnsembleSolver:
    """우선순위 순서의 백엔드 solver들을 다수결로 결합.

    solvers[0]가 가장 강한 백엔드(동률 tie-break의 우선권). mode/model은 벤치마크 호환용.
    """

    solvers: list[Solver]
    labels: list[str]
    mode: str = "ensemble"
    model: str = "ensemble"

    def solve(self, question: dict[str, Any]) -> SolveResult:
        results = [s.solve(question) for s in self.solvers]
        per_backend = {lbl: r.chosen_index for lbl, r in zip(self.labels, results, strict=False)}
        votes = [r.chosen_index for r in results if r.chosen_index >= 0]

        if not votes:
            chosen, agreement, unanimous = -1, 0.0, False
        else:
            counts = Counter(votes)
            top_count = counts.most_common(1)[0][1]
            tied = {idx for idx, c in counts.items() if c == top_count}
            # 동률이면 우선순위(앞쪽=강한 백엔드)가 고른 top 답을 채택.
            chosen = next((r.chosen_index for r in results if r.chosen_index in tied), votes[0])
            agreement = top_count / len(votes)
            unanimous = len(set(votes)) == 1 and len(votes) == len(self.solvers)

        lines = [f"앙상블({'+'.join(self.labels)}) — 합의도 {agreement:.0%}"]
        for lbl, r in zip(self.labels, results, strict=False):
            lines.append(f"- {lbl}: {r.chosen_index}")
        lines.append(f"정답 확정(다수결+우선순위): {chosen}")
        lines.append(f"ANSWER: {chosen}" if chosen >= 0 else "INSUFFICIENT EVIDENCE")
        rationale = "\n".join(lines)

        return SolveResult(
            question_id=question["question_id"],
            chosen_index=chosen,
            rationale=rationale,
            mode="ensemble",
            model=self.model,
            raw_response=rationale,
            tool_calls=[
                {
                    "tool": "cross_model_ensemble",
                    "backends": list(self.labels),
                    "backend_answers": per_backend,
                    "agreement": round(agreement, 3),
                    "unanimous": unanimous,
                    # 합의 신뢰 신호: 만장일치(자동 신뢰 권장) vs 불일치(검토/RAG 라우팅).
                    "confidence": round(agreement, 3),
                }
            ],
        )


def create_ensemble_solver(
    backends: list[str],
    *,
    rag_dir: Any = None,
    model: str | None = None,
    solvers: list[Solver] | None = None,
) -> EnsembleSolver:
    """backends 순서 = 우선순위(강한 백엔드 먼저, 예: ['codex', 'anthropic']).

    solvers를 직접 주입하면(테스트/커스텀) 그대로 사용. label은 backends를 그대로 쓴다.
    """
    if len(backends) < 2:
        raise ValueError("ensemble은 backend 2개 이상 필요")
    label = "ensemble:" + "+".join(backends)
    if solvers is not None:
        if len(solvers) != len(backends):
            raise ValueError("solvers 길이와 backends 길이가 달라야 함")
        return EnsembleSolver(solvers=list(solvers), labels=list(backends), model=label)

    from cpa_first.solver.solver import create_solver

    built = [create_solver(mode="live", backend=b, rag_dir=rag_dir, model=model) for b in backends]
    return EnsembleSolver(solvers=built, labels=list(backends), model=label)
