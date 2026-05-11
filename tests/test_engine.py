"""처방 엔진 단위 테스트.

07-implementation-plan.md §1의 검증 목표 3개를 입증한다.
1) 결정론: 동일 입력 → 동일 출력
2) 근거 추적: 모든 처방에 evidence_refs >= 1
3) 민감도: 사용자 상태 변화 → 처방 변화
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from cpa_first.engine import (
    load_decision_rules,
    load_problem_intelligence,
    load_user_state,
    prescribe,
)


ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = ROOT / "data" / "seeds" / "decision_rules"
USER_STATES_DIR = ROOT / "data" / "seeds" / "user_states"
PROBLEMS_DIR = ROOT / "data" / "seeds" / "problems"
SCHEMA_PATH = ROOT / "data" / "schemas" / "prescription.schema.json"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"

FIXED_TS = "2026-05-11T04:00:00+00:00"


@pytest.fixture(scope="module")
def rules() -> list[dict]:
    return load_decision_rules(RULES_DIR)


@pytest.fixture(scope="module")
def problems() -> list[dict]:
    return load_problem_intelligence(PROBLEMS_DIR)


@pytest.fixture(scope="module")
def prescription_validator() -> Draft202012Validator:
    with SCHEMA_PATH.open("r", encoding="utf-8") as f:
        return Draft202012Validator(json.load(f))


@pytest.fixture(scope="module")
def all_user_states() -> dict[str, dict]:
    return {
        path.stem: load_user_state(path)
        for path in sorted(USER_STATES_DIR.glob("user_state_*.json"))
    }


def test_seed_files_present(rules, all_user_states):
    assert len(rules) >= 5, "최소 5건 decision_rule이 필요"
    assert len(all_user_states) == 5, "단계별 5건 user_state가 필요"


@pytest.mark.parametrize(
    "user_state_path",
    sorted(USER_STATES_DIR.glob("user_state_*.json")),
    ids=lambda p: p.stem,
)
def test_all_prescriptions_pass_schema(user_state_path, rules, prescription_validator):
    user_state = load_user_state(user_state_path)
    rx = prescribe(user_state, rules, generated_at=FIXED_TS)
    errors = sorted(prescription_validator.iter_errors(rx), key=lambda e: list(e.path))
    assert not errors, "\n".join(
        f"[{'/'.join(str(p) for p in e.path) or '<root>'}] {e.message}" for e in errors
    )


@pytest.mark.parametrize(
    "user_state_path",
    sorted(USER_STATES_DIR.glob("user_state_*.json")),
    ids=lambda p: p.stem,
)
def test_deterministic_output(user_state_path, rules):
    """검증 목표 1: 같은 입력은 같은 출력."""
    user_state = load_user_state(user_state_path)
    rx_a = prescribe(user_state, rules, generated_at=FIXED_TS)
    rx_b = prescribe(user_state, rules, generated_at=FIXED_TS)
    assert json.dumps(rx_a, sort_keys=True, ensure_ascii=False) == json.dumps(
        rx_b, sort_keys=True, ensure_ascii=False
    )


def test_deterministic_independent_of_rule_order(all_user_states, rules):
    """매칭 정렬이 결정론적이므로 입력 rule 순서가 달라도 출력 동일."""
    user_state = all_user_states["user_state_mock_exam"]
    rx_normal = prescribe(user_state, rules, generated_at=FIXED_TS)
    rx_shuffled = prescribe(user_state, list(reversed(rules)), generated_at=FIXED_TS)
    assert rx_normal == rx_shuffled


@pytest.mark.parametrize(
    "user_state_path",
    sorted(USER_STATES_DIR.glob("user_state_*.json")),
    ids=lambda p: p.stem,
)
def test_evidence_refs_attached(user_state_path, rules):
    """검증 목표 2: 모든 처방에 근거 추적 가능. user_state + 매칭 규칙 수만큼."""
    user_state = load_user_state(user_state_path)
    rx = prescribe(user_state, rules, generated_at=FIXED_TS)

    assert len(rx["evidence_refs"]) >= 1
    expected = 1 + len(rx["triggered_rule_keys"])  # user_state ref 1개 + 규칙별 ref
    assert len(rx["evidence_refs"]) == expected

    ref_types = {ref["ref_type"] for ref in rx["evidence_refs"]}
    assert "user_state" in ref_types
    if rx["triggered_rule_keys"]:
        assert "decision_rule" in ref_types


def test_sensitivity_across_stages(all_user_states, rules):
    """검증 목표 3: 단계별로 처방의 핵심 필드가 달라진다."""
    triggered_per_stage = {
        stem: tuple(prescribe(state, rules, generated_at=FIXED_TS)["triggered_rule_keys"])
        for stem, state in all_user_states.items()
    }
    # 5개 단계 시드 중 적어도 3가지 이상 서로 다른 규칙 조합이 나와야 함
    unique = set(triggered_per_stage.values())
    assert len(unique) >= 3, f"단계별 처방 다양성 부족: {triggered_per_stage}"


def test_sensitivity_risk_level(all_user_states, rules):
    """매칭 수와 잔여 기간 차이로 risk_level이 다르게 나오는 사용자가 존재."""
    risk_levels = {
        stem: prescribe(state, rules, generated_at=FIXED_TS)["diagnosis"]["risk_level"]
        for stem, state in all_user_states.items()
    }
    assert len(set(risk_levels.values())) >= 2, f"risk_level 차별성 없음: {risk_levels}"


def test_stage_filter_changes_matching(all_user_states, rules):
    """current_stage만 바꿔도 매칭이 달라져야 한다."""
    base = copy.deepcopy(all_user_states["user_state_objective_entry"])
    base_keys = prescribe(base, rules, generated_at=FIXED_TS)["triggered_rule_keys"]

    mutated = copy.deepcopy(base)
    mutated["current_stage"] = "intro"  # 어떤 규칙도 intro 단계에 매칭되지 않음
    intro_keys = prescribe(mutated, rules, generated_at=FIXED_TS)["triggered_rule_keys"]

    # intro 단계 매칭은 더 적거나 다름. base 키들과 동일하면 안 됨.
    assert intro_keys != base_keys
    # post_lecture/objective_entry/past_exam_rotation/mock_exam/final 외 단계에서
    # applicable_stages 매칭이 줄어 매칭 수 ≤ 매칭 수가 됨
    assert len(intro_keys) <= len(base_keys)


def test_risk_tag_filter_blocks_match():
    """required_risk_tags가 있는 규칙은 사용자에 해당 태그가 없으면 매칭 안 됨."""
    rule = {
        "rule_key": "test_rule",
        "rule_name": "테스트 규칙",
        "condition_text": "",
        "action_text": "행동",
        "exception_text": None,
        "applicable_stages": [],
        "applicable_subjects": [],
        "required_risk_tags": ["memory_decay"],
        "source_signal_count": 1,
        "source_case_ids": [],
        "confidence": 0.7,
        "review_status": "approved",
    }
    user_with_tag = {
        "user_id": "u1",
        "target_exam": "CPA_1",
        "days_until_exam": 100,
        "available_hours_per_day": 8,
        "current_stage": "objective_entry",
        "subject_states": [
            {
                "subject": "tax",
                "accuracy": 0.5,
                "time_overrun_rate": 0.1,
                "risk_tags": ["memory_decay"],
            }
        ],
    }
    user_without_tag = copy.deepcopy(user_with_tag)
    user_without_tag["user_id"] = "u2"
    user_without_tag["subject_states"][0]["risk_tags"] = ["other_tag"]

    assert prescribe(user_with_tag, [rule], generated_at=FIXED_TS)["triggered_rule_keys"] == [
        "test_rule"
    ]
    assert prescribe(user_without_tag, [rule], generated_at=FIXED_TS)["triggered_rule_keys"] == []


def test_accounting_tax_subject_requires_both():
    """applicable_subjects=['accounting_tax']는 사용자가 두 과목을 모두 가질 때만 매칭."""
    rule = {
        "rule_key": "accounting_tax_test",
        "rule_name": "회계세법 양축",
        "condition_text": "",
        "action_text": "행동",
        "exception_text": None,
        "applicable_stages": [],
        "applicable_subjects": ["accounting_tax"],
        "required_risk_tags": [],
        "source_signal_count": 1,
        "source_case_ids": [],
        "confidence": 0.7,
        "review_status": "approved",
    }
    user_both = {
        "user_id": "u1",
        "target_exam": "CPA_1",
        "days_until_exam": 100,
        "available_hours_per_day": 8,
        "current_stage": "objective_entry",
        "subject_states": [
            {"subject": "accounting", "accuracy": 0.5, "time_overrun_rate": 0.1, "risk_tags": []},
            {"subject": "tax", "accuracy": 0.5, "time_overrun_rate": 0.1, "risk_tags": []},
        ],
    }
    user_only_tax = {
        "user_id": "u2",
        "target_exam": "CPA_1",
        "days_until_exam": 100,
        "available_hours_per_day": 8,
        "current_stage": "objective_entry",
        "subject_states": [
            {"subject": "tax", "accuracy": 0.5, "time_overrun_rate": 0.1, "risk_tags": []},
        ],
    }

    assert prescribe(user_both, [rule], generated_at=FIXED_TS)["triggered_rule_keys"] == [
        "accounting_tax_test"
    ]
    assert prescribe(user_only_tax, [rule], generated_at=FIXED_TS)["triggered_rule_keys"] == []


def test_daily_tasks_non_empty(all_user_states, rules):
    """매칭이 없어도 placeholder task 하나는 채워져야 한다(스키마 minItems=1)."""
    for stem, state in all_user_states.items():
        rx = prescribe(state, rules, generated_at=FIXED_TS)
        assert len(rx["daily_tasks"]) >= 1, f"{stem}: daily_tasks 비어있음"


@pytest.mark.parametrize(
    "user_state_path",
    sorted(USER_STATES_DIR.glob("user_state_*.json")),
    ids=lambda p: p.stem,
)
def test_prescription_snapshot(user_state_path, rules, problems):
    """현재 알고리즘+시드 데이터의 처방 출력을 스냅샷과 비교한다.

    의도된 변경이라면 tests/snapshots/<stem>.snap.json을 수동 갱신한 뒤 재실행.
    """
    user_state = load_user_state(user_state_path)
    rx = prescribe(user_state, rules, generated_at=FIXED_TS, problem_intel=problems)

    snapshot_path = SNAPSHOT_DIR / f"{user_state_path.stem}.snap.json"
    assert snapshot_path.exists(), (
        f"snapshot 누락: {snapshot_path}. 시드 데이터/알고리즘 추가 시 함께 갱신해야 한다."
    )
    with snapshot_path.open("r", encoding="utf-8") as f:
        expected = json.load(f)

    assert rx == expected, (
        f"처방이 스냅샷과 다름. 의도된 변경이면 {snapshot_path.name}을 갱신."
    )


def test_concepts_to_review_sorted_by_mastery(all_user_states, rules):
    """약점 개념이 먼저 와야 한다."""
    state = copy.deepcopy(all_user_states["user_state_objective_entry"])
    rx = prescribe(state, rules, generated_at=FIXED_TS)
    concepts = rx["concepts_to_review"]
    assert concepts, "concept_mastery가 있으면 비어있을 수 없음"

    # 원본 상태에서 mastery 낮은 N개 확인
    flat: list[tuple[float, str]] = []
    for s in state["subject_states"]:
        for cm in s.get("concept_mastery") or []:
            flat.append((cm["mastery"], cm["concept"]))
    flat.sort()
    expected_top = [c[1] for c in flat[: len(concepts)]]
    assert concepts == expected_top
