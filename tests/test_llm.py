"""LLM invoke 어댑터 테스트 — 실제 codex/ollama/anthropic 호출 없이 (mock)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cpa_first import llm


def test_resolve_backend_precedence(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("CPA_LLM_BACKEND", raising=False)
    assert llm.resolve_backend() == "codex"  # 기본
    monkeypatch.setenv("CPA_LLM_BACKEND", "ollama")
    assert llm.resolve_backend() == "ollama"  # env
    assert llm.resolve_backend("anthropic") == "anthropic"  # 인자 우선


def test_make_invoke_unknown_backend():
    with pytest.raises(llm.InvokeError):
        llm.make_invoke("gpt9")


def test_make_invoke_returns_callable_without_calling(monkeypatch: pytest.MonkeyPatch):
    # codex/ollama invoke 생성만 — 실제 호출 안 함.
    assert callable(llm.make_invoke("codex"))
    assert callable(llm.make_invoke("ollama"))


def test_codex_invoke_builds_command_and_parses_output(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_run(cmd, input=None, capture_output=None, text=None, timeout=None):
        captured["cmd"] = cmd
        captured["input"] = input
        out_path = cmd[cmd.index("-o") + 1]
        Path(out_path).write_text("풀이 근거...\nANSWER: 2", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    out = llm.codex_invoke("시스템 지시", "문제 본문", model="o3")

    assert out.strip().endswith("ANSWER: 2")
    assert captured["cmd"][:2] == ["codex", "exec"]
    assert "--skip-git-repo-check" in captured["cmd"]
    assert "-m" in captured["cmd"] and "o3" in captured["cmd"]
    # system + user가 stdin 프롬프트에 합쳐졌는지
    assert "시스템 지시" in captured["input"] and "문제 본문" in captured["input"]


def test_codex_invoke_not_found(monkeypatch: pytest.MonkeyPatch):
    def boom(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(llm.subprocess, "run", boom)
    with pytest.raises(llm.InvokeError):
        llm.codex_invoke("s", "u")


def test_create_solver_uses_injected_invoke():
    from cpa_first.solver import create_solver

    calls = {}

    def fake_invoke(system: str, user: str) -> str:
        calls["user"] = user
        return "풀이: ...\nANSWER: 1"

    solver = create_solver(mode="live", invoke=fake_invoke)
    q = {
        "question_id": "q1",
        "subject": "accounting",
        "unit": "재무회계",
        "stem": "문제?",
        "choices": ["a", "b", "c", "d"],
    }
    res = solver.solve(q)
    assert res.chosen_index == 1
    assert res.mode == "live"
    assert "문제?" in calls["user"]


def test_create_solver_codex_backend_builds_without_calling(monkeypatch: pytest.MonkeyPatch):
    from cpa_first.solver import create_solver

    solver = create_solver(mode="live", backend="codex")
    assert solver.mode == "live"
    assert solver.invoke is not None
    assert "codex" in solver.model
