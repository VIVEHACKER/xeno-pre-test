"""과목별 백엔드 라우팅 solver 테스트 — fake invoke(실제 LLM 호출 없음)."""

from __future__ import annotations

import pytest

from cpa_first.solver import RoutingSolver, create_solver, parse_routes
from cpa_first.solver.routing import RoutingSolver as _RS
from cpa_first.solver.solver import Solver

TAX_Q = {
    "question_id": "tax-1",
    "subject": "tax",
    "unit": "income_tax",
    "stem": "세법 문제?",
    "choices": ["a", "b", "c", "d"],
}
ACC_Q = {
    "question_id": "acc-1",
    "subject": "accounting",
    "unit": "재무회계",
    "stem": "회계 문제?",
    "choices": ["a", "b", "c", "d"],
}


def _solver(answer: int):
    def inv(system: str, user: str) -> str:
        return f"풀이...\nANSWER: {answer}"

    return Solver(mode="live", invoke=inv)


def test_parse_routes():
    assert parse_routes("tax:codex") == {"tax": "codex"}
    assert parse_routes("tax:codex, corporate_law:Codex") == {
        "tax": "codex",
        "corporate_law": "codex",
    }
    assert parse_routes("") == {}
    assert parse_routes(None) == {}


def test_parse_routes_rejects_bad_format():
    with pytest.raises(ValueError):
        parse_routes("tax-codex")


def test_routes_to_matching_backend():
    rs = RoutingSolver(routes={"tax": _solver(2)}, default=_solver(0))
    assert rs.solve(TAX_Q).chosen_index == 2  # 세법 → 라우팅된 solver


def test_falls_back_to_default():
    rs = RoutingSolver(routes={"tax": _solver(2)}, default=_solver(0))
    assert rs.solve(ACC_Q).chosen_index == 0  # 비세법 → default


def test_unmapped_subject_uses_default():
    rs = RoutingSolver(routes={}, default=_solver(3))
    assert rs.solve(TAX_Q).chosen_index == 3


def test_env_routes_does_not_override_explicit_mode(monkeypatch):
    """CPA_LLM_ROUTES가 켜져 있어도 mode='mock'은 mock을 반환해야 한다(P2 회귀방지)."""
    monkeypatch.setenv("CPA_LLM_ROUTES", "tax:codex")
    s = create_solver(mode="mock")
    assert not isinstance(s, _RS)
    assert s.mode == "mock"


def test_env_routes_does_not_override_explicit_backends(monkeypatch):
    """CPA_LLM_ROUTES가 켜져 있어도 명시 backends(앙상블)가 우선한다."""
    from cpa_first.solver import EnsembleSolver

    monkeypatch.setenv("CPA_LLM_ROUTES", "tax:codex")
    s = create_solver(mode="live", backends=["codex", "ollama"])
    assert not isinstance(s, _RS)
    assert isinstance(s, EnsembleSolver)


def test_env_routes_activates_only_in_live(monkeypatch):
    """live 모드 + 주입 invoke 없을 때만 env 라우팅 발동."""
    monkeypatch.setenv("CPA_LLM_ROUTES", "tax:codex")
    monkeypatch.setenv("CPA_LLM_BACKEND", "ollama")
    s = create_solver(mode="live")
    assert isinstance(s, _RS)


def test_explicit_invoke_beats_env_routes(monkeypatch):
    """주입 invoke가 있으면 env 라우팅보다 우선(테스트 주입 보호)."""
    monkeypatch.setenv("CPA_LLM_ROUTES", "tax:codex")
    s = create_solver(mode="live", invoke=lambda sy, u: "ANSWER: 0")
    assert not isinstance(s, _RS)
