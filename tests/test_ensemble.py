"""교차-모델 앙상블 solver 테스트 — fake invoke (실제 codex/anthropic 호출 없음)."""

from __future__ import annotations

import pytest

from cpa_first.solver import EnsembleSolver, create_ensemble_solver, create_solver
from cpa_first.solver.solver import Solver

Q = {
    "question_id": "q1",
    "subject": "accounting",
    "unit": "재무회계",
    "stem": "문제?",
    "choices": ["a", "b", "c", "d"],
}


def _solver(answer):
    """answer가 0~3이면 'ANSWER: n' 반환, None이면 기권(ANSWER 없음)."""

    def inv(system: str, user: str) -> str:
        return f"풀이...\nANSWER: {answer}" if answer is not None else "근거 부족"

    return Solver(mode="live", invoke=inv)


def _ens(answers, backends=None):
    backends = backends or [f"b{i}" for i in range(len(answers))]
    return EnsembleSolver(solvers=[_solver(a) for a in answers], labels=backends)


def test_majority_vote():
    res = _ens([1, 1, 2]).solve(Q)
    assert res.chosen_index == 1
    tc = res.tool_calls[0]
    assert tc["agreement"] == pytest.approx(2 / 3, abs=1e-3)
    assert tc["unanimous"] is False
    assert tc["backend_answers"] == {"b0": 1, "b1": 1, "b2": 2}
    assert res.mode == "ensemble"


def test_unanimous():
    res = _ens([0, 0, 0]).solve(Q)
    assert res.chosen_index == 0
    assert res.tool_calls[0]["agreement"] == 1.0
    assert res.tool_calls[0]["unanimous"] is True


def test_tie_breaks_by_priority():
    # 동률(2:2) → 우선순위(앞쪽 강한 백엔드)가 고른 답 채택.
    res = _ens([2, 3, 2, 3], backends=["strong", "b1", "b2", "b3"]).solve(Q)
    # strong이 2를 골랐고 2도 top-count → 2 채택
    assert res.chosen_index == 2


def test_two_way_tie_priority():
    res = _ens([0, 1], backends=["strong", "weak"]).solve(Q)
    assert res.chosen_index == 0  # 동률 → strong(우선)
    assert res.tool_calls[0]["agreement"] == pytest.approx(0.5)


def test_all_abstain():
    res = _ens([None, None]).solve(Q)
    assert res.chosen_index == -1
    assert res.tool_calls[0]["agreement"] == 0.0
    assert "INSUFFICIENT EVIDENCE" in res.rationale


def test_partial_abstain_uses_valid_votes():
    # 한 백엔드 기권, 둘은 동일 → 그 답 채택
    res = _ens([1, None, 1]).solve(Q)
    assert res.chosen_index == 1


def test_create_ensemble_requires_two():
    with pytest.raises(ValueError):
        create_ensemble_solver(["codex"])


def test_create_solver_backends_builds_ensemble():
    # codex/ollama는 키 없이 빌드 가능(make_invoke 람다, 실제 호출 안 함).
    solver = create_solver(backends=["codex", "ollama"])
    assert isinstance(solver, EnsembleSolver)
    assert solver.labels == ["codex", "ollama"]
    assert len(solver.solvers) == 2
    assert "codex" in solver.model and "ollama" in solver.model


def test_ensemble_runs_through_benchmark():
    """production 벤치마크 파이프라인이 EnsembleSolver를 그대로 채점한다."""
    from cpa_first.benchmark.runner import run_benchmark

    questions = [
        {
            "question_id": "e1",
            "subject": "accounting",
            "unit": "u",
            "stem": "s",
            "choices": ["a", "b", "c", "d"],
            "correct_choice": 1,
        },
        {
            "question_id": "e2",
            "subject": "tax",
            "unit": "u",
            "stem": "s",
            "choices": ["a", "b", "c", "d"],
            "correct_choice": 0,
        },
    ]
    # 두 백엔드가 합의로 1을 고름 → e1 정답(1), e2 오답(정답 0)
    ens = _ens([1, 1], backends=["codex", "anthropic"])
    res = run_benchmark(questions=questions, solver=ens, persist=False)
    assert res.solver_mode == "ensemble"
    assert res.total == 2
    assert res.correct == 1  # e1만 정답
    # 합의 신뢰 신호가 풀이에 보존됨
    assert "앙상블" in res.questions[0].rationale
