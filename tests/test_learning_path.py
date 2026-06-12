"""학습 경로 엔진 단위 테스트.

검증 목표:
1) 순서: 깊은 선수개념이 먼저, 약점 자체가 마지막 (depth 내림차순)
2) depth 제한: max_depth 밖 선수개념은 제외
3) 순환 방어: prerequisite 순환 그래프에서도 종료 + 중복 없음
4) 매칭: 콜론 라벨 부분 매칭, alias 매칭, 실패 시 unmatched_concepts
5) 절단: max_nodes 초과 시 depth 0 우선 보존
6) 자원: to_kind별 상위 weight 순 최대 3개
7) 결정론: 동일 입력 → 동일 출력
8) 실데이터 스모크: TermIndex.from_paths + 시드 terms로 경로 산출
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from cpa_first.engine.learning_path import build_learning_path
from cpa_first.rag import TermIndex

ROOT = Path(__file__).resolve().parents[1]
TERMS_DIR = ROOT / "data" / "seeds" / "terms"
EDGES_PATH = ROOT / "data" / "seeds" / "term_graph" / "edges.jsonl"


# ── 인라인 fixture ──────────────────────────────────────────────


def _term(term_id: str, name_ko: str, **overrides) -> dict:
    base = {
        "term_id": term_id,
        "name_ko": name_ko,
        "aliases": [],
        "subject": "accounting",
        "difficulty": "core",
        "prerequisite_terms": [],
        "confusable_with": [],
    }
    base.update(overrides)
    return base


@pytest.fixture()
def terms_full() -> dict[str, dict]:
    """ecl → ac → eir 2단 선수 사슬 + confusable + alias를 갖춘 소형 그래프."""
    return {
        "ecl": _term(
            "ecl",
            "기대신용손실",
            aliases=["ECL"],
            prerequisite_terms=["ac"],
            confusable_with=[
                {"term_id": "impairment", "reason": "손상차손은 결과, ECL은 측정 모형"},
                {"term_id": "ghost", "reason": "시드에 없는 용어"},
            ],
        ),
        "ac": _term("ac", "상각후원가", prerequisite_terms=["eir"]),
        "eir": _term("eir", "유효이자율"),
        "impairment": _term("impairment", "손상차손"),
        "fv": _term("fv", "공정가치", subject="accounting"),
    }


@pytest.fixture()
def edges() -> list[dict]:
    """dict 형태 엣지 — 엔진이 Edge dataclass와 dict 모두 지원하는지 함께 검증."""
    return [
        {
            "from_term": "ac",
            "to_kind": "rag_chunk",
            "to_id": "chunk-low",
            "relation": "defined_in",
            "weight": 1.0,
        },
        {
            "from_term": "ac",
            "to_kind": "rag_chunk",
            "to_id": "chunk-high",
            "relation": "defined_in",
            "weight": 3.0,
        },
        {
            "from_term": "ac",
            "to_kind": "rag_chunk",
            "to_id": "chunk-mid2",
            "relation": "explained_in",
            "weight": 2.0,
        },
        {
            "from_term": "ac",
            "to_kind": "rag_chunk",
            "to_id": "chunk-mid1",
            "relation": "defined_in",
            "weight": 2.0,
        },
        {
            "from_term": "ac",
            "to_kind": "problem",
            "to_id": "prob-1",
            "relation": "tested_in",
            "weight": 2.0,
        },
        {
            "from_term": "ac",
            "to_kind": "tutorial",
            "to_id": "tut-1",
            "relation": "explained_in",
            "weight": 1.5,
        },
        # to_kind=term 엣지는 자원이 아니므로 무시되어야 한다
        {
            "from_term": "ac",
            "to_kind": "term",
            "to_id": "eir",
            "relation": "prerequisite_of",
            "weight": 1.0,
        },
    ]


# ── 순서 / depth ────────────────────────────────────────────────


def test_prerequisites_come_first(terms_full, edges):
    result = build_learning_path(["재무회계: 기대신용손실"], terms_full, edges)
    ids = [p["term_id"] for p in result["path"]]
    assert ids == ["eir", "ac", "ecl"], "깊은 선수개념(depth 2)부터 약점(depth 0) 순서"
    depths = [p["depth"] for p in result["path"]]
    assert depths == [2, 1, 0]
    assert result["unmatched_concepts"] == []


def test_why_traces_root_concept(terms_full, edges):
    result = build_learning_path(["재무회계: 기대신용손실"], terms_full, edges)
    by_id = {p["term_id"]: p for p in result["path"]}
    assert "기대신용손실" in by_id["ecl"]["why"]
    assert "상각후원가" in by_id["eir"]["why"], "직접 선수 관계인 부모 용어를 명시"
    assert "1단계" in by_id["ac"]["why"]
    assert "2단계" in by_id["eir"]["why"]


def test_max_depth_limits_backtracking(terms_full, edges):
    result = build_learning_path(["기대신용손실"], terms_full, edges, max_depth=1)
    ids = [p["term_id"] for p in result["path"]]
    assert ids == ["ac", "ecl"], "depth 2(eir)는 max_depth=1에서 제외"


def test_cycle_safe():
    cyclic = {
        "a": _term("a", "가나다라", prerequisite_terms=["b"]),
        "b": _term("b", "마바사아", prerequisite_terms=["a"]),
    }
    result = build_learning_path(["가나다라"], cyclic, [], max_depth=5)
    ids = [p["term_id"] for p in result["path"]]
    assert ids == ["b", "a"], "순환에서도 종료하고 각 term은 한 번만 등장"


def test_weak_concept_that_is_also_prerequisite_stays_depth0(terms_full, edges):
    """약점 두 개가 서로 선수 관계면 둘 다 depth 0으로 보존된다."""
    result = build_learning_path(["기대신용손실", "상각후원가"], terms_full, edges)
    by_id = {p["term_id"]: p for p in result["path"]}
    assert by_id["ecl"]["depth"] == 0
    assert by_id["ac"]["depth"] == 0
    assert by_id["eir"]["depth"] == 1


# ── 매칭 ────────────────────────────────────────────────────────


def test_colon_label_partial_match(terms_full, edges):
    result = build_learning_path(["재무회계: 유효이자율"], terms_full, edges)
    assert [p["term_id"] for p in result["path"]] == ["eir"]


def test_alias_match(terms_full, edges):
    result = build_learning_path(["회계: ECL 모형"], terms_full, edges)
    assert result["path"][-1]["term_id"] == "ecl", "alias(ECL)가 라벨에 포함되면 매칭"


def test_unmatched_concepts_reported(terms_full, edges):
    result = build_learning_path(["경영학: 블록체인 거버넌스", "기대신용손실"], terms_full, edges)
    assert result["unmatched_concepts"] == ["경영학: 블록체인 거버넌스"]
    assert any(p["term_id"] == "ecl" for p in result["path"])


def test_all_unmatched_returns_empty_path(terms_full, edges):
    result = build_learning_path(["없는개념"], terms_full, edges)
    assert result["path"] == []
    assert result["unmatched_concepts"] == ["없는개념"]
    assert result["evidence_refs"] == []


# ── 절단 (max_nodes) ───────────────────────────────────────────


def test_max_nodes_preserves_depth0_first(terms_full, edges):
    result = build_learning_path(["기대신용손실", "공정가치"], terms_full, edges, max_nodes=2)
    ids = {p["term_id"] for p in result["path"]}
    assert ids == {"ecl", "fv"}, "선수개념(ac, eir)보다 약점 자체(depth 0)를 우선 보존"
    assert len(result["path"]) == 2


# ── 자원 / confusable ──────────────────────────────────────────


def test_resources_top3_by_weight(terms_full, edges):
    result = build_learning_path(["상각후원가"], terms_full, edges)
    ac = next(p for p in result["path"] if p["term_id"] == "ac")
    chunks = ac["resources"]["chunks"]
    assert len(chunks) == 3, "chunk 엣지 4개 중 상위 weight 3개만"
    assert chunks[0] == {"chunk_id": "chunk-high", "weight": 3.0}
    assert [c["chunk_id"] for c in chunks] == ["chunk-high", "chunk-mid1", "chunk-mid2"], (
        "weight 내림차순, 동률은 chunk_id 오름차순"
    )
    assert ac["resources"]["problems"] == [{"problem_id": "prob-1", "weight": 2.0}]
    assert ac["resources"]["tutorials"] == [{"tutorial_id": "tut-1", "weight": 1.5}]


def test_resources_empty_when_no_edges(terms_full, edges):
    result = build_learning_path(["유효이자율"], terms_full, edges)
    eir = result["path"][0]
    assert eir["resources"] == {"chunks": [], "problems": [], "tutorials": []}


def test_confusable_with_resolved_names(terms_full, edges):
    result = build_learning_path(["기대신용손실"], terms_full, edges)
    ecl = next(p for p in result["path"] if p["term_id"] == "ecl")
    assert ecl["confusable_with"] == [
        {
            "term_id": "impairment",
            "name_ko": "손상차손",
            "reason": "손상차손은 결과, ECL은 측정 모형",
        }
    ], "시드에 없는 confusable(ghost)은 제외"


# ── 근거 추적 / 결정론 ──────────────────────────────────────────


def test_evidence_refs_cover_every_path_node(terms_full, edges):
    result = build_learning_path(["기대신용손실"], terms_full, edges)
    assert len(result["evidence_refs"]) == len(result["path"]) >= 1
    for ref in result["evidence_refs"]:
        assert ref["ref_type"] == "term"
        assert ref["ref_id"]
        assert ref["note"], "모든 참조에 한국어 근거 문장"


def test_deterministic(terms_full, edges):
    weak = ["기대신용손실", "공정가치", "없는개념"]
    first = build_learning_path(weak, copy.deepcopy(terms_full), copy.deepcopy(edges))
    second = build_learning_path(weak, copy.deepcopy(terms_full), copy.deepcopy(edges))
    assert json.dumps(first, ensure_ascii=False, sort_keys=True) == json.dumps(
        second, ensure_ascii=False, sort_keys=True
    )


def test_input_not_mutated(terms_full, edges):
    snapshot = copy.deepcopy(terms_full)
    build_learning_path(["기대신용손실"], terms_full, edges)
    assert terms_full == snapshot


# ── 실데이터 스모크 ─────────────────────────────────────────────


def test_real_seed_smoke():
    index = TermIndex.from_paths(TERMS_DIR, EDGES_PATH)
    terms_full = {}
    for path in sorted(TERMS_DIR.glob("*.term.json")):
        with path.open("r", encoding="utf-8") as f:
            term = json.load(f)
        terms_full[term["term_id"]] = term

    result = build_learning_path(["재무회계: 기대신용손실"], terms_full, index.edges)

    ids = [p["term_id"] for p in result["path"]]
    assert ids == ["effective-interest-rate", "amortized-cost", "expected-credit-loss"], (
        "시드 그래프의 2단 선수 사슬: 유효이자율 → 상각후원가 → 기대신용손실"
    )
    assert result["unmatched_concepts"] == []

    ac = next(p for p in result["path"] if p["term_id"] == "amortized-cost")
    assert any(c["chunk_id"] == "kifrs-1109-amortized-cost" for c in ac["resources"]["chunks"]), (
        "defined_in 엣지의 chunk가 자원으로 연결"
    )
    assert any(pr["problem_id"] == "cpa1-accounting-002" for pr in ac["resources"]["problems"]), (
        "tested_in 엣지의 problem이 자원으로 연결"
    )

    for entry in result["path"]:
        assert entry["name_ko"]
        assert entry["subject"]
        assert entry["why"]
    assert len(result["evidence_refs"]) == len(result["path"])
