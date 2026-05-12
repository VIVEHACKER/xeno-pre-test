"""Phase 3 — 용어 지식 그래프 빌더 단위 테스트.

검증 범위:
  - 스키마 자체 유효성 (Draft 2020-12 meta-schema)
  - 시드 인스턴스가 스키마를 통과한다
  - 빌더의 결정론 (동일 입력 → 동일 출력)
  - 각 매처가 의도한 엣지를 만든다 (defined_in, tested_in, explained_in, confusable_with, prerequisite_of)
  - _contains의 단어 경계가 ASCII 단축어 오매칭을 막는다 (예: "AC"가 "WACC"에 매치 금지)
  - edges.jsonl 한 줄 한 줄이 term_edge 스키마를 통과한다
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import build_term_graph as builder  # noqa: E402


SCHEMA_DIR = ROOT / "data" / "schemas"
TERMS_DIR = ROOT / "data" / "seeds" / "terms"
EDGES_PATH = ROOT / "data" / "seeds" / "term_graph" / "edges.jsonl"


# ── 스키마 자체 검증 ─────────────────────────────────────────────


def test_term_schema_meta_valid():
    schema = json.loads((SCHEMA_DIR / "term.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


def test_term_edge_schema_meta_valid():
    schema = json.loads((SCHEMA_DIR / "term_edge.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


# ── 시드 인스턴스 검증 ───────────────────────────────────────────


def test_all_term_seeds_pass_schema():
    schema = json.loads((SCHEMA_DIR / "term.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    failures: list[tuple[str, list[str]]] = []
    for path in sorted(TERMS_DIR.glob("*.term.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        errors = [str(e.message) for e in validator.iter_errors(data)]
        if errors:
            failures.append((path.name, errors))
    assert not failures, f"seed validation failed: {failures}"


def test_term_seeds_have_unique_ids():
    ids = [
        json.loads(p.read_text(encoding="utf-8"))["term_id"]
        for p in TERMS_DIR.glob("*.term.json")
    ]
    assert len(ids) == len(set(ids)), f"duplicate term_ids: {ids}"


def test_negative_term_instance_is_rejected():
    """schema가 잘못된 enum/pattern/빈 문자열을 모두 거부해야 한다."""
    schema = json.loads((SCHEMA_DIR / "term.schema.json").read_text(encoding="utf-8"))
    bad = {
        "term_id": "Bad_ID",       # uppercase + underscore 위반
        "name_ko": "",              # minLength 위반
        "subject": "unknown",       # enum 위반
        "definition": "x",
        "difficulty": "medium",     # enum 위반
        "rights_status": "x",       # enum 위반
        "review_status": "x",       # enum 위반
    }
    errors = list(Draft202012Validator(schema).iter_errors(bad))
    assert len(errors) >= 4


# ── _contains: 단어 경계 ──────────────────────────────────────────


def test_contains_ascii_word_boundary():
    # "AC"가 "WACC" 안에 있어도 매치하면 안 됨
    assert not builder._contains("WACC", "AC")
    assert not builder._contains("CAPM", "AP")
    # 단어로 떨어져 있으면 매치
    assert builder._contains("AC를 사용한다", "AC")
    assert builder._contains("결과는 AC.", "AC")


def test_contains_korean_substring():
    # 한글은 substring 매칭 (단어 경계 X)
    assert builder._contains("상각후원가 측정", "상각후원가")
    assert builder._contains("재무회계: 금융자산", "재무회계")


# ── 매처 ────────────────────────────────────────────────────────


def _term(term_id: str, name_ko: str, **extra) -> dict:
    base = {
        "term_id": term_id,
        "name_ko": name_ko,
        "name_en": None,
        "aliases": [],
        "subject": "accounting",
        "unit": None,
        "definition": "x",
        "formula": None,
        "difficulty": "intermediate",
        "confusable_with": [],
        "prerequisite_terms": [],
        "example": None,
        "rights_status": "self_generated",
        "review_status": "ai_draft",
    }
    base.update(extra)
    return base


def test_defined_in_keyword_beats_body():
    terms = [_term("amortized-cost", "상각후원가", aliases=["AC"])]
    chunks = [{
        "chunk_id": "chunk-a",
        "keywords": ["상각후원가"],
        "text": "이 청크는 상각후원가에 관한 글이다.",
    }]
    edges = builder.edges_to_rag(terms, chunks)
    assert len(edges) == 1
    assert edges[0].weight == 2.0
    assert "keyword match" in edges[0].evidence


def test_defined_in_body_fallback():
    terms = [_term("amortized-cost", "상각후원가")]
    chunks = [{
        "chunk_id": "chunk-b",
        "keywords": [],
        "text": "본문에 상각후원가가 등장하지만 keywords에는 없다.",
    }]
    edges = builder.edges_to_rag(terms, chunks)
    assert len(edges) == 1
    assert edges[0].weight == 1.0


def test_tested_in_exact_match():
    terms = [_term("wacc", "WACC")]
    problems = [{
        "problem_id": "p1",
        "required_concepts": [{"concept": "WACC", "role": "x"}],
        "concept_tags": [],
    }]
    edges = builder.edges_to_problems(terms, problems)
    assert len(edges) == 1
    assert edges[0].weight == 2.0


def test_tested_in_partial_match_via_tags():
    terms = [_term("wacc", "WACC")]
    problems = [{
        "problem_id": "p2",
        "required_concepts": [],
        "concept_tags": ["재무관리: WACC"],
    }]
    edges = builder.edges_to_problems(terms, problems)
    assert len(edges) == 1
    assert edges[0].weight == 1.0


def test_tested_in_no_ascii_false_positive():
    """alias 'AC'는 'WACC' 안에 substring으로 있지만 매치하면 안 됨."""
    terms = [_term("amortized-cost", "상각후원가", aliases=["AC"])]
    problems = [{
        "problem_id": "p3",
        "required_concepts": [{"concept": "WACC", "role": "x"}],
        "concept_tags": ["MM_proposition"],
    }]
    edges = builder.edges_to_problems(terms, problems)
    assert edges == [], f"unexpected match: {edges}"


def test_explained_in_tutorial_body():
    terms = [_term("standard-cost", "표준원가")]
    tutorials = [{
        "tutorial_id": "tut-1",
        "title": "원가 차이 분석",
        "steps": ["표준원가를 잡고 차이를 분해한다"],
    }]
    edges = builder.edges_to_tutorials(terms, tutorials)
    assert len(edges) == 1
    assert edges[0].relation == "explained_in"


def test_confusable_with_bidirectional():
    terms = [
        _term("a", "용어A", confusable_with=[{"term_id": "b", "reason": "헷갈림"}]),
        _term("b", "용어B"),
    ]
    edges = builder.edges_confusable(terms)
    pairs = {(e.from_term, e.to_id) for e in edges}
    assert ("a", "b") in pairs
    assert ("b", "a") in pairs


def test_prerequisite_of_reverse_direction():
    """'A의 prereq가 B'이면 빌더는 B --prerequisite_of--> A 를 만들어야 한다."""
    terms = [
        _term("a", "용어A", prerequisite_terms=["b"]),
        _term("b", "용어B"),
    ]
    edges = builder.edges_prerequisite(terms)
    assert len(edges) == 1
    assert edges[0].from_term == "b"
    assert edges[0].to_id == "a"
    assert edges[0].relation == "prerequisite_of"


# ── 통합 + 결정론 ─────────────────────────────────────────────────


def test_build_edges_dedupes_by_max_weight():
    """같은 (from, to_kind, to_id, relation)이 여러 weight로 나오면 큰 것만 남긴다."""
    terms = [_term("amortized-cost", "상각후원가", aliases=["AC"])]
    chunks = [{
        "chunk_id": "c1",
        "keywords": ["상각후원가"],            # 2.0
        "text": "본문에도 상각후원가가 있다.",   # 1.0
    }]
    edges = builder.build_edges(terms, chunks, [], [])
    rag_edges = [e for e in edges if e.relation == "defined_in"]
    assert len(rag_edges) == 1
    assert rag_edges[0].weight == 2.0


def test_build_edges_deterministic(tmp_path):
    """전체 빌더가 결정론적이다 — 같은 입력 2회 실행 → 동일 edges.jsonl."""
    edges1 = builder.build_edges(
        builder.load_terms(TERMS_DIR),
        builder.load_chunks(ROOT / "data" / "seeds" / "rag"),
        builder.load_problems(ROOT / "data" / "seeds" / "problems"),
        builder.load_tutorials(ROOT / "data" / "seeds" / "subject_tutorials.json"),
    )
    edges2 = builder.build_edges(
        builder.load_terms(TERMS_DIR),
        builder.load_chunks(ROOT / "data" / "seeds" / "rag"),
        builder.load_problems(ROOT / "data" / "seeds" / "problems"),
        builder.load_tutorials(ROOT / "data" / "seeds" / "subject_tutorials.json"),
    )
    assert [e.to_dict() for e in edges1] == [e.to_dict() for e in edges2]

    # 파일 write 후 byte-identical도 확인
    out1 = tmp_path / "e1.jsonl"
    out2 = tmp_path / "e2.jsonl"
    builder.write_edges(edges1, out1)
    builder.write_edges(edges2, out2)
    assert out1.read_bytes() == out2.read_bytes()


# ── edges.jsonl 회귀 ─────────────────────────────────────────────


def test_emitted_edges_pass_schema():
    """현재 커밋된 edges.jsonl이 모두 스키마를 통과한다."""
    if not EDGES_PATH.exists():
        pytest.skip("edges.jsonl이 아직 생성되지 않았다 (build_term_graph.py 실행 필요)")
    schema = json.loads((SCHEMA_DIR / "term_edge.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    failures: list[tuple[int, list[str]]] = []
    with EDGES_PATH.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            edge = json.loads(line)
            errors = [e.message for e in validator.iter_errors(edge)]
            if errors:
                failures.append((i, errors))
    assert not failures, f"edge validation failed: {failures}"


def test_emitted_edges_have_no_ac_false_positive():
    """회귀: 'AC' alias가 'WACC' 안에 substring 매치하던 버그가 재발하면 실패."""
    if not EDGES_PATH.exists():
        pytest.skip("edges.jsonl이 아직 생성되지 않았다")
    with EDGES_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            edge = json.loads(line)
            if edge["from_term"] == "amortized-cost" and edge["to_kind"] == "problem":
                evidence = edge.get("evidence") or ""
                # WACC 문제(cpa1-business-004)에 AC가 매치되면 안 됨
                assert "AC" not in evidence or "concept_tags" not in evidence, (
                    f"AC false-positive regression: {edge}"
                )
