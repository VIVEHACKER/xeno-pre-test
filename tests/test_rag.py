"""RAG 검색 단위 테스트 + solver context 주입 통합."""

from __future__ import annotations

from pathlib import Path

import pytest

from cpa_first.rag import (
    RagChunk,
    format_context,
    load_chunks,
    retrieve,
)
from cpa_first.solver import Solver, create_solver


ROOT = Path(__file__).resolve().parents[1]
RAG_DIR = ROOT / "data" / "seeds" / "rag"


@pytest.fixture(scope="module")
def chunks() -> list[RagChunk]:
    return load_chunks(RAG_DIR)


def test_load_chunks_count(chunks):
    assert len(chunks) >= 5


def test_retrieve_financial_assets_query(chunks):
    hits = retrieve(
        "유효이자율로 이자수익을 어떻게 계산하나요?",
        chunks,
        subject="accounting",
        unit="financial_assets",
    )
    assert hits, "금융자산 관련 chunk가 반환되어야 함"
    assert hits[0].chunk.chunk_id == "kifrs-1109-amortized-cost"


def test_retrieve_subject_filter_excludes_other(chunks):
    """tax subject query는 accounting chunk를 후보로 두지 않는다."""
    hits = retrieve("부가가치세 면세", chunks, subject="tax")
    assert hits
    for hit in hits:
        assert hit.chunk.subject in {"tax", "general"}


def test_retrieve_deterministic(chunks):
    a = retrieve("CVP 공헌이익 안전한계", chunks, subject="accounting")
    b = retrieve("CVP 공헌이익 안전한계", chunks, subject="accounting")
    assert [h.chunk.chunk_id for h in a] == [h.chunk.chunk_id for h in b]


def test_retrieve_sorted_by_score_then_id(chunks):
    hits = retrieve("회계 세법 일반", chunks, top_k=10)
    scores = [(h.score, h.chunk.chunk_id) for h in hits]
    # 점수 desc, id asc 순서
    for i in range(len(scores) - 1):
        a, b = scores[i], scores[i + 1]
        assert (a[0] > b[0]) or (a[0] == b[0] and a[1] <= b[1])


def test_retrieve_empty_query_returns_nothing(chunks):
    assert retrieve("!!!", chunks, subject="accounting") == []


def test_retrieve_min_score_filters_noise(chunks):
    """매우 무관한 쿼리는 min_score로 컷."""
    # 일부러 chunk 본문/태그와 겹치지 않는 쿼리
    hits = retrieve("pizza basketball weather", chunks, min_score=2.0)
    assert hits == []


def test_format_context_serializes_hits(chunks):
    hits = retrieve("유효이자율 이자수익", chunks, subject="accounting", top_k=1)
    text = format_context(hits)
    assert "참고 자료" in text
    assert hits[0].chunk.title in text


def test_format_context_empty():
    assert format_context([]) == ""


# ----- Solver RAG 통합 -----


SAMPLE_Q = {
    "question_id": "rag-int-1",
    "exam": "CPA_1",
    "subject": "accounting",
    "unit": "financial_assets",
    "stem": "유효이자율법으로 첫 해 이자수익을 계산하시오.",
    "choices": ["a", "b", "c", "d"],
    "correct_choice": 1,
    "rights_status": "synthetic_seed",
    "review_status": "expert_reviewed",
}


def test_create_solver_with_rag_dir_loads_chunks():
    solver = create_solver(mode="mock", rag_dir=RAG_DIR)
    assert len(solver.rag_chunks) >= 5


def test_live_solver_includes_rag_context_in_user_message(chunks):
    captured: dict[str, str] = {}

    def fake_invoke(system: str, user: str) -> str:
        captured["user"] = user
        return "ANSWER: 1"

    solver = Solver(mode="live", invoke=fake_invoke, rag_chunks=chunks, rag_top_k=2)
    solver.solve(SAMPLE_Q)
    assert "참고 자료" in captured["user"]
    assert "유효이자율" in captured["user"]


def test_live_solver_without_rag_omits_context(chunks):
    captured: dict[str, str] = {}

    def fake_invoke(system: str, user: str) -> str:
        captured["user"] = user
        return "ANSWER: 1"

    solver = Solver(mode="live", invoke=fake_invoke)
    solver.solve(SAMPLE_Q)
    assert "참고 자료" not in captured["user"]


def test_mock_solver_ignores_rag(chunks):
    """mock은 결정론 stub. rag_chunks가 있어도 출력 동일."""
    a = Solver(mode="mock").solve(SAMPLE_Q)
    b = Solver(mode="mock", rag_chunks=chunks).solve(SAMPLE_Q)
    assert a.chosen_index == b.chosen_index
