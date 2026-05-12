"""Phase 4 — term_index + search 통합 테스트.

검증:
  - 로더: load_terms / load_edges 가 시드 디렉토리에서 정상 로드
  - matched_terms: 쿼리 표면형 매칭 (단어 경계 ASCII, substring 한글)
  - expand_query: 매칭 term의 표면형 + 시드 내 confusable 표면형 포함
  - related_chunks: term의 defined_in 엣지 → chunk_id 목록
  - search 통합: term_index 인자가 점수 +0.5 가산 (Red-Green)
  - 회귀: term_index=None일 때 기존 점수와 동일 (이전 동작 호환)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cpa_first.rag import (
    Edge,
    RagChunk,
    Term,
    TermIndex,
    load_chunks,
    load_edges,
    load_terms,
    retrieve,
)


ROOT = Path(__file__).resolve().parents[1]
RAG_DIR = ROOT / "data" / "seeds" / "rag"
TERMS_DIR = ROOT / "data" / "seeds" / "terms"
EDGES_PATH = ROOT / "data" / "seeds" / "term_graph" / "edges.jsonl"


# ── fixtures ────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def chunks() -> list[RagChunk]:
    return load_chunks(RAG_DIR)


@pytest.fixture(scope="module")
def index() -> TermIndex:
    return TermIndex.from_paths(TERMS_DIR, EDGES_PATH)


# ── 로더 ────────────────────────────────────────────────────────


def test_load_terms_count():
    terms = load_terms(TERMS_DIR)
    # Phase 2: 15개, Phase 4 확장: 100+. 향후 시드 추가에도 회귀 검증 유지.
    assert len(terms) >= 100
    ids = {t.term_id for t in terms}
    assert "amortized-cost" in ids
    assert "wacc" in ids


def test_load_edges_returns_objects():
    edges = load_edges(EDGES_PATH)
    assert edges, "edges.jsonl이 비어있다 (build_term_graph.py를 먼저 실행)"
    assert all(isinstance(e, Edge) for e in edges)
    # 빌더가 생성한 결과와 동일 개수
    assert any(e.relation == "defined_in" for e in edges)
    assert any(e.relation == "confusable_with" for e in edges)


def test_load_edges_returns_empty_on_missing(tmp_path):
    assert load_edges(tmp_path / "nope.jsonl") == []


# ── matched_terms ────────────────────────────────────────────────


def test_matched_terms_korean_name(index):
    assert "amortized-cost" in index.matched_terms("상각후원가 계산법")


def test_matched_terms_alias(index):
    # 'EIR'은 effective-interest-rate의 alias
    assert "effective-interest-rate" in index.matched_terms("EIR을 적용한다")


def test_matched_terms_no_ascii_false_positive(index):
    """alias 'AC'(amortized-cost)는 'WACC' 안에 substring으로 있지만 매치 금지."""
    matched = index.matched_terms("WACC를 계산하시오")
    assert "amortized-cost" not in matched
    assert "wacc" in matched


def test_matched_terms_empty_for_unrelated_query(index):
    assert index.matched_terms("점심으로 김밥을 먹었다") == set()


# ── expand_query ─────────────────────────────────────────────────


def test_expand_query_includes_aliases(index):
    expanded = index.expand_query("유효이자율을 사용한다")
    # name_ko + aliases 모두 포함되어야 함
    assert "유효이자율" in expanded
    assert "유효이자율법" in expanded
    assert "EIR" in expanded


def test_expand_query_includes_in_seed_confusable(index):
    """종합과세 ↔ 분리과세는 시드 내 confusable 쌍."""
    expanded = index.expand_query("종합과세 기준금액")
    # comprehensive-taxation 본인의 표면형
    assert "종합과세" in expanded
    # 시드 내 confusable인 separate-taxation의 표면형까지 확장
    assert "분리과세" in expanded


def test_expand_query_skips_out_of_seed_confusable(index):
    """current-tax(시드 외)는 deferred-tax의 confusable이지만 확장에 안 들어옴."""
    expanded = index.expand_query("이연법인세 인식")
    assert "이연법인세" in expanded  # 본인 표면형은 들어옴
    # current-tax는 시드에 없으므로 표면형도 알 수 없음
    assert "당기법인세" not in expanded
    assert "current-tax" not in expanded


def test_expand_query_empty_for_unrelated(index):
    assert index.expand_query("점심으로 김밥") == set()


# ── related_chunks / chunk_defined_by ───────────────────────────


def test_related_chunks_for_amortized_cost(index):
    chunks = index.related_chunks("amortized-cost")
    assert "kifrs-1109-amortized-cost" in chunks


def test_chunk_defined_by_reverse_lookup(index):
    terms = index.chunk_defined_by("kifrs-1109-amortized-cost")
    # 이 chunk는 amortized-cost, effective-interest-rate, expected-credit-loss 셋 모두의 keyword 매치 (빌더 결과)
    assert "amortized-cost" in terms
    assert "effective-interest-rate" in terms
    assert "expected-credit-loss" in terms


# ── search 통합: 점수 부스트 (Red-Green) ─────────────────────────


def test_term_index_boosts_score(chunks, index):
    """term_index가 있으면 그래프 일치 chunk의 점수가 더 높아야 한다."""
    query = "상각후원가를 어떻게 계산하지"

    baseline = retrieve(query, chunks, subject="accounting", top_k=5)
    boosted = retrieve(query, chunks, subject="accounting", top_k=5, term_index=index)

    base_score = {h.chunk.chunk_id: h.score for h in baseline}
    boost_score = {h.chunk.chunk_id: h.score for h in boosted}

    target = "kifrs-1109-amortized-cost"
    assert target in base_score, "baseline에서 target chunk가 안 나옴"
    assert target in boost_score, "term_index 적용 시 target chunk가 안 나옴"
    # 그래프 보너스 +0.5 (확장 토큰으로 인한 본문 매칭 추가도 가능 → 더 클 수 있음)
    assert boost_score[target] >= base_score[target] + 0.5


def test_term_index_none_preserves_baseline(chunks):
    """term_index=None이면 Phase 4 이전 동작과 점수가 정확히 같다."""
    query = "유효이자율로 이자수익을 어떻게 계산하나요?"
    a = retrieve(query, chunks, subject="accounting", unit="financial_assets")
    b = retrieve(
        query, chunks, subject="accounting", unit="financial_assets", term_index=None
    )
    assert [(h.chunk.chunk_id, h.score) for h in a] == [
        (h.chunk.chunk_id, h.score) for h in b
    ]


def test_term_index_expansion_finds_chunk_via_alias(chunks, index):
    """쿼리에 alias만 있어도 확장 후 본문 매칭으로 chunk를 찾는다."""
    # 'EIR'만 쓰는 영문 쿼리. 확장 없이는 'eir'이 chunk 본문에 없어 못 찾음.
    hits = retrieve("EIR 적용", chunks, subject="accounting", term_index=index)
    chunk_ids = [h.chunk.chunk_id for h in hits]
    assert "kifrs-1109-amortized-cost" in chunk_ids


def test_term_index_irrelevant_query_unchanged(chunks, index):
    """쿼리에 어떤 term도 매칭되지 않으면 점수 변화 없음."""
    # 시드 어느 것의 name_ko/aliases도 포함하지 않는 비CPA 쿼리
    query = "점심 메뉴 결정"
    assert index.matched_terms(query) == set(), "테스트 전제: 어떤 term도 매치되면 안 됨"
    a = retrieve(query, chunks, subject="accounting", top_k=5)
    b = retrieve(query, chunks, subject="accounting", top_k=5, term_index=index)
    assert [(h.chunk.chunk_id, h.score) for h in a] == [
        (h.chunk.chunk_id, h.score) for h in b
    ]


def test_red_green_term_addition_changes_score(chunks):
    """Red-Green 검증: 빈 인덱스 → term 추가 → 점수 상승 → 제거 → 원복."""
    query = "상각후원가 측정"
    target = "kifrs-1109-amortized-cost"

    # 빈 인덱스 (term/edge 없음) → term_index=None과 같은 baseline
    empty = TermIndex(terms=[], edges=[])
    hits_empty = retrieve(query, chunks, subject="accounting", term_index=empty)
    score_empty = {h.chunk.chunk_id: h.score for h in hits_empty}[target]

    # term 1개만 추가 (엣지 없음) → matched_terms는 잡히지만 chunk_defined_by가 비어 부스트 없음
    term = Term(term_id="amortized-cost", name_ko="상각후원가")
    only_term = TermIndex(terms=[term], edges=[])
    hits_term = retrieve(query, chunks, subject="accounting", term_index=only_term)
    score_term = {h.chunk.chunk_id: h.score for h in hits_term}[target]
    assert score_term == score_empty, "엣지 없는 인덱스가 점수를 바꾸면 안 됨"

    # 엣지 추가 → 부스트 적용
    edge = Edge(
        from_term="amortized-cost",
        to_kind="rag_chunk",
        to_id=target,
        relation="defined_in",
        weight=2.0,
    )
    with_edge = TermIndex(terms=[term], edges=[edge])
    hits_edge = retrieve(query, chunks, subject="accounting", term_index=with_edge)
    score_edge = {h.chunk.chunk_id: h.score for h in hits_edge}[target]
    assert score_edge == round(score_empty + 0.5, 4)

    # 엣지 제거 → 원복
    rolled_back = TermIndex(terms=[term], edges=[])
    hits_back = retrieve(query, chunks, subject="accounting", term_index=rolled_back)
    score_back = {h.chunk.chunk_id: h.score for h in hits_back}[target]
    assert score_back == score_empty
