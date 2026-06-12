"""학습 로드맵 생성기(study_plan) 단위 테스트.

검증 목표:
1) D-day별 주차 수와 단계 압축 (D-90 / D-30 / D-7)
2) 과락 위험 과목 시간 가중 + floor 보장
3) 빈 subject_states 폴백 (진단 보강 1주)
4) 결정론: 동일 입력 → 동일 출력
5) 주간 시간 합계 = hours_per_week (±0.1)
"""

from __future__ import annotations

import copy
import json

from cpa_first.engine.study_plan import (
    FAIL_RISK_FLOOR_RATIO,
    MAINTENANCE_RATIO,
    STAGE_ORDER,
    build_study_plan,
)


def make_user_state(
    days: int = 90,
    hours: float = 4.0,
    stage: str = "post_lecture",
    subject_states: list[dict] | None = None,
) -> dict:
    if subject_states is None:
        subject_states = [
            {"subject": "accounting", "accuracy": 0.65, "time_overrun_rate": 0.20, "risk_tags": []},
            {
                "subject": "tax",
                "accuracy": 0.35,
                "time_overrun_rate": 0.40,
                "risk_tags": ["concept_gap"],
            },
            {"subject": "business", "accuracy": 0.78, "time_overrun_rate": 0.10, "risk_tags": []},
            {
                "subject": "corporate_law",
                "accuracy": 0.55,
                "time_overrun_rate": 0.25,
                "risk_tags": [],
            },
            {"subject": "economics", "accuracy": 0.60, "time_overrun_rate": 0.20, "risk_tags": []},
        ]
    return {
        "user_id": "u-test",
        "target_exam": "CPA_1",
        "days_until_exam": days,
        "available_hours_per_day": hours,
        "current_stage": stage,
        "subject_states": subject_states,
    }


def _alloc_hours(week: dict) -> dict[str, float]:
    return {item["subject"]: item["hours"] for item in week["subject_allocation"]}


# ---------------------------------------------------------------- D-day별 주차/단계


def test_d90_week_count_and_stage_progression():
    """D-90: 13주 플랜, post_lecture부터 final까지 단계가 순서대로 진행된다."""
    plan = build_study_plan(make_user_state(days=90, stage="post_lecture"))

    assert plan["total_weeks"] == 13  # ceil(90/7)
    assert len(plan["weeks"]) == 13
    assert [w["week_no"] for w in plan["weeks"]] == list(range(1, 14))

    assert plan["weeks"][0]["stage"] == "post_lecture"
    assert plan["weeks"][-1]["stage"] == "final"
    # 단계는 STAGE_ORDER를 따라 단조 진행 (역행 금지)
    indices = [STAGE_ORDER.index(w["stage"]) for w in plan["weeks"]]
    assert indices == sorted(indices)
    # 잔여 5단계가 모두 포함된다 (충분한 주 → 비례 배분)
    assert {w["stage"] for w in plan["weeks"]} == set(STAGE_ORDER[1:])


def test_d30_compression_one_week_per_stage():
    """D-30: 5주 = 잔여 5단계 경계 → 단계당 1주씩 압축 배분."""
    plan = build_study_plan(make_user_state(days=30, stage="post_lecture"))

    assert plan["total_weeks"] == 5
    assert [w["stage"] for w in plan["weeks"]] == [
        "post_lecture",
        "objective_entry",
        "past_exam_rotation",
        "mock_exam",
        "final",
    ]


def test_d7_compression_keeps_final_stage():
    """D-7: 1주뿐이면 시험에 가까운 뒤 단계(final)만 남긴다."""
    plan = build_study_plan(make_user_state(days=7, stage="post_lecture"))

    assert plan["total_weeks"] == 1
    assert len(plan["weeks"]) == 1
    assert plan["weeks"][0]["stage"] == "final"


def test_max_weeks_cap():
    """D-200이라도 max_weeks=16으로 상한."""
    plan = build_study_plan(make_user_state(days=200))
    assert plan["total_weeks"] == 16
    assert len(plan["weeks"]) == 16


def test_days_range_format():
    plan = build_study_plan(make_user_state(days=90))
    assert plan["weeks"][0]["days_range"] == "D-90~D-84"
    assert plan["weeks"][1]["days_range"] == "D-83~D-77"


def test_last_week_is_failure_defense_check():
    """모든 D-day에서 마지막 주는 모의/최종 점검 + 과락 방어 milestone."""
    for days in (90, 30, 7):
        plan = build_study_plan(make_user_state(days=days))
        last = plan["weeks"][-1]
        assert "과락" in last["milestone"], f"D-{days}: 과락 방어 체크 누락"
        assert "40%" in last["verification_metric"]
        assert "60%" in last["verification_metric"]


# ---------------------------------------------------------------- 과목 시간 배분


def test_fail_risk_subject_gets_most_hours_and_floor():
    """과락 위험 과목(tax, 35%)이 최다 시간 + floor(주간 15%) 보장."""
    plan = build_study_plan(make_user_state())
    alloc = _alloc_hours(plan["weeks"][0])

    assert alloc["tax"] == max(alloc.values())
    assert alloc["tax"] > alloc["accounting"]
    assert alloc["tax"] >= plan["hours_per_week"] * FAIL_RISK_FLOOR_RATIO - 0.01


def test_stable_subject_gets_maintenance_only():
    """안정 과목(business, 78%)은 망각 방지 유지 시간만 받는다."""
    plan = build_study_plan(make_user_state())
    alloc = _alloc_hours(plan["weeks"][0])

    assert alloc["business"] == min(alloc.values())
    expected_maintenance = plan["hours_per_week"] * MAINTENANCE_RATIO
    assert abs(alloc["business"] - expected_maintenance) <= 0.1


def test_all_subjects_present_every_week_with_positive_hours():
    """망각 방지: 모든 주에 전 과목이 0보다 큰 시간으로 배정된다."""
    plan = build_study_plan(make_user_state(days=90))
    subjects = {"accounting", "tax", "business", "corporate_law", "economics"}
    for week in plan["weeks"]:
        alloc = _alloc_hours(week)
        assert set(alloc) == subjects, f"{week['week_no']}주차 과목 누락"
        assert all(h > 0 for h in alloc.values()), f"{week['week_no']}주차 0시간 과목 존재"


def test_hours_sum_matches_hours_per_week():
    """모든 주의 과목 시간 합계가 hours_per_week와 일치(±0.1)."""
    plan = build_study_plan(make_user_state(days=90, hours=4.0))
    assert plan["hours_per_week"] == 28.0
    for week in plan["weeks"]:
        total = sum(item["hours"] for item in week["subject_allocation"])
        assert abs(total - plan["hours_per_week"]) <= 0.1, f"{week['week_no']}주차 합계 {total}"


def test_all_fail_risk_subjects_still_sum_correctly():
    """전 과목 과락 위험이어도 합계 보존 + 균형 배분."""
    states = [
        {"subject": s, "accuracy": 0.30, "time_overrun_rate": 0.3, "risk_tags": []}
        for s in ("accounting", "tax", "business", "corporate_law", "economics")
    ]
    plan = build_study_plan(make_user_state(subject_states=states))
    alloc = _alloc_hours(plan["weeks"][0])
    assert abs(sum(alloc.values()) - plan["hours_per_week"]) <= 0.1
    for hours in alloc.values():
        assert hours >= plan["hours_per_week"] * FAIL_RISK_FLOOR_RATIO - 0.01


# ---------------------------------------------------------------- 폴백/결정론/근거


def test_empty_subject_states_fallback():
    """subject_states가 비면 진단 보강 1주 플랜으로 폴백."""
    plan = build_study_plan(make_user_state(days=90, subject_states=[]))

    assert plan["total_weeks"] == 1
    assert len(plan["weeks"]) == 1
    week = plan["weeks"][0]
    assert "진단" in week["theme"]
    assert week["verification_metric"]
    # 폴백도 CPA 1차 5과목 균등 배정 + 합계 보존
    alloc = _alloc_hours(week)
    assert set(alloc) == {"accounting", "tax", "business", "corporate_law", "economics"}
    assert abs(sum(alloc.values()) - plan["hours_per_week"]) <= 0.1


def test_deterministic_output():
    """동일 입력 → 동일 출력. 입력도 변형하지 않는다."""
    state = make_user_state(days=90)
    snapshot = copy.deepcopy(state)

    plan_a = build_study_plan(state)
    plan_b = build_study_plan(state)

    assert json.dumps(plan_a, sort_keys=True, ensure_ascii=False) == json.dumps(
        plan_b, sort_keys=True, ensure_ascii=False
    )
    assert state == snapshot, "입력 user_state가 변형됨"


def test_pass_bar_and_evidence_refs():
    """합격 기준 명시 + evidence_refs 호환 구조로 근거 추적 가능."""
    plan = build_study_plan(make_user_state())

    assert plan["pass_bar"] == {"average": 0.60, "per_subject_floor": 0.40}

    refs = plan["evidence_refs"]
    assert len(refs) >= 1
    assert all({"ref_type", "ref_id", "note"} <= set(r) for r in refs)
    ref_types = {r["ref_type"] for r in refs}
    assert "user_state" in ref_types
    assert "subject_state" in ref_types


def test_every_week_has_reason_and_metric():
    """모든 주에 한국어 검증 지표, 모든 배분에 한국어 이유."""
    plan = build_study_plan(make_user_state(days=90))
    for week in plan["weeks"]:
        assert week["verification_metric"].strip()
        assert week["theme"].strip()
        assert week["milestone"].strip()
        for item in week["subject_allocation"]:
            assert item["reason"].strip(), f"{week['week_no']}주차 {item['subject']} 이유 누락"


def test_strategy_summary_mentions_plan_shape():
    plan = build_study_plan(make_user_state(days=90))
    summary = plan["strategy_summary"]
    assert "13주" in summary
    assert "과락" in summary
