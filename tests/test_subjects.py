"""과목 레지스트리 단위 테스트.

레지스트리가 단일 진실원이 되어야 한다. 스키마 enum과 레지스트리가
일치하는지, 매칭 헬퍼가 일반화된 동작을 보장하는지 검증.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cpa_first.subjects import (
    GROUPS,
    SUBJECTS,
    WILDCARD,
    all_subject_ids,
    is_group,
    is_known_subject,
    matches_rule_subject,
    name_ko,
    primary_subject,
    schema_enum_rule_subjects,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "data" / "schemas"


def _schema_subject_enum(filename: str, *json_path: str) -> list[str]:
    with (SCHEMA_DIR / filename).open("r", encoding="utf-8") as f:
        node = json.load(f)
    for key in json_path:
        node = node[key]
    return list(node["enum"])


def test_registry_includes_required_subjects():
    """요청한 6과목 + 기존 누적 과목이 등록되어야 한다."""
    required = {
        "accounting",
        "tax",
        "finance",
        "corporate_law",
        "economics",
        "cost_accounting",
    }
    assert required.issubset(set(all_subject_ids()))


@pytest.mark.parametrize(
    "filename,path",
    [
        ("problem_intelligence.schema.json", ("properties", "subject")),
        ("evaluation_question.schema.json", ("properties", "subject")),
        (
            "user_state.schema.json",
            (
                "properties",
                "subject_states",
                "items",
                "properties",
                "subject",
            ),
        ),
    ],
)
def test_subject_enum_matches_registry(filename: str, path: tuple[str, ...]):
    """문제/평가/사용자 스키마의 subject enum은 레지스트리와 일치."""
    enum = _schema_subject_enum(filename, *path)
    assert enum == all_subject_ids()


@pytest.mark.parametrize(
    "filename,path",
    [
        ("rag_chunk.schema.json", ("properties", "subject")),
        ("term.schema.json", ("properties", "subject")),
    ],
)
def test_subject_enum_with_wildcard(filename: str, path: tuple[str, ...]):
    """RAG/Term 스키마는 'general' 와일드카드 포함."""
    enum = _schema_subject_enum(filename, *path)
    assert enum == all_subject_ids() + [WILDCARD]


def test_decision_rule_enum_matches_registry():
    enum = _schema_subject_enum(
        "decision_rule.schema.json", "properties", "applicable_subjects", "items"
    )
    assert enum == schema_enum_rule_subjects()


def test_is_known_subject():
    for sid in SUBJECTS:
        assert is_known_subject(sid)
    assert not is_known_subject("biology")
    assert not is_known_subject("")


def test_is_group_and_members():
    assert is_group("accounting_tax")
    assert not is_group("accounting")
    assert GROUPS["accounting_tax"] == frozenset({"accounting", "tax"})


def test_name_ko():
    assert name_ko("accounting") == "회계"
    assert name_ko("finance") == "재무관리"
    # 알 수 없는 id는 그대로 (UI fallback)
    assert name_ko("unknown_x") == "unknown_x"


def test_matches_rule_subject_general():
    assert matches_rule_subject(WILDCARD, set())
    assert matches_rule_subject(WILDCARD, {"finance"})


def test_matches_rule_subject_single():
    assert matches_rule_subject("finance", {"finance", "tax"})
    assert not matches_rule_subject("finance", {"tax"})


def test_matches_rule_subject_group_requires_all_members():
    assert matches_rule_subject("accounting_tax", {"accounting", "tax"})
    assert not matches_rule_subject("accounting_tax", {"accounting"})
    assert not matches_rule_subject("accounting_tax", {"tax"})


def test_matches_rule_subject_unknown_returns_false():
    assert not matches_rule_subject("not_a_subject", {"accounting", "tax"})


def test_primary_subject_single_returns_subject():
    assert primary_subject(["finance"], {"finance"}) == "finance"
    assert primary_subject(["cost_accounting"], {"cost_accounting"}) == "cost_accounting"


def test_primary_subject_multiple_returns_mixed():
    assert primary_subject(["accounting", "tax"], {"accounting", "tax"}) == "mixed"


def test_primary_subject_group_returns_mixed():
    """그룹 id는 단일 과목 task로 귀속할 수 없으므로 mixed."""
    assert primary_subject(["accounting_tax"], {"accounting", "tax"}) == "mixed"


def test_primary_subject_no_user_match_returns_mixed():
    assert primary_subject(["finance"], {"tax"}) == "mixed"
