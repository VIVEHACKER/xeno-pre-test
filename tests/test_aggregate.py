"""aggregate.py — MistakeLog → UserState 산출 단위 테스트."""

from __future__ import annotations

from cpa_first.engine import (
    aggregate_subject_state,
    aggregate_user_state,
    infer_current_stage,
)


PROBLEMS = [
    {
        "problem_id": "P-A1",
        "subject": "accounting",
        "time_strategy": {"target_seconds": 90, "skip_threshold_seconds": 120, "exam_room_rule": ""},
    },
    {
        "problem_id": "P-A2",
        "subject": "accounting",
        "time_strategy": {"target_seconds": 100, "skip_threshold_seconds": 130, "exam_room_rule": ""},
    },
    {
        "problem_id": "P-T1",
        "subject": "tax",
        "time_strategy": {"target_seconds": 95, "skip_threshold_seconds": 125, "exam_room_rule": ""},
    },
]


def _log(problem_id: str, correct: bool, time_seconds: int, *, mistakes: list[str] | None = None) -> dict:
    return {
        "log_id": f"L-{problem_id}-{time_seconds}",
        "user_id": "u",
        "problem_id": problem_id,
        "attempt_at": "2026-05-11T00:00:00+00:00",
        "correct": correct,
        "time_seconds": time_seconds,
        "mistake_categories": mistakes or [],
    }


def test_aggregate_subject_state_basic():
    pbi = {p["problem_id"]: p for p in PROBLEMS}
    logs = [
        _log("P-A1", True, 80),
        _log("P-A1", False, 150, mistakes=["time_pressure", "condition_miss"]),
        _log("P-A2", True, 90),
        _log("P-A2", False, 140, mistakes=["time_pressure"]),
    ]
    agg = aggregate_subject_state(logs, pbi, "accounting")
    assert agg is not None
    assert agg["subject"] == "accounting"
    assert agg["accuracy"] == 0.5
    # 4건 중 시간초과 2건 (150>120, 140>130)
    assert agg["time_overrun_rate"] == 0.5
    # time_pressure 2회 (1위), condition_miss 1회 (2위)
    assert agg["risk_tags"][0] == "time_pressure"
    assert "condition_miss" in agg["risk_tags"]


def test_aggregate_subject_state_empty():
    assert aggregate_subject_state([], {}, "accounting") is None


def test_aggregate_subject_state_no_threshold():
    """time_strategy 없는 problem은 time_overrun 계산에서 제외."""
    pbi = {"X": {"problem_id": "X", "subject": "tax"}}
    logs = [_log("X", True, 200), _log("X", False, 300)]
    agg = aggregate_subject_state(logs, pbi, "tax")
    assert agg is not None
    assert agg["time_overrun_rate"] == 0.0
    assert agg["accuracy"] == 0.5


def test_aggregate_user_state_separates_subjects():
    logs = [
        _log("P-A1", True, 80),
        _log("P-A2", False, 200, mistakes=["concept_gap"]),
        _log("P-T1", True, 70),
        _log("P-T1", False, 160, mistakes=["memory_decay"]),
    ]
    us = aggregate_user_state(
        logs,
        PROBLEMS,
        user_id="u1",
        target_exam="CPA_1",
        days_until_exam=90,
        available_hours_per_day=8,
        current_stage="objective_entry",
    )
    assert us["user_id"] == "u1"
    assert us["current_stage"] == "objective_entry"
    subjects = {s["subject"]: s for s in us["subject_states"]}
    assert set(subjects) == {"accounting", "tax"}
    assert subjects["accounting"]["accuracy"] == 0.5
    assert subjects["tax"]["accuracy"] == 0.5
    assert "concept_gap" in subjects["accounting"]["risk_tags"]
    assert "memory_decay" in subjects["tax"]["risk_tags"]


def test_aggregate_user_state_deterministic():
    logs = [
        _log("P-A1", True, 80),
        _log("P-A2", False, 200, mistakes=["concept_gap", "time_pressure"]),
        _log("P-T1", False, 130, mistakes=["memory_decay"]),
    ]
    a = aggregate_user_state(
        logs, PROBLEMS, user_id="u", target_exam="CPA_1",
        days_until_exam=90, available_hours_per_day=8, current_stage="objective_entry",
    )
    b = aggregate_user_state(
        list(reversed(logs)), PROBLEMS, user_id="u", target_exam="CPA_1",
        days_until_exam=90, available_hours_per_day=8, current_stage="objective_entry",
    )
    assert a == b


def test_aggregate_user_state_unknown_problem_ignored():
    logs = [
        _log("UNKNOWN", True, 50),
        _log("P-A1", True, 80),
    ]
    us = aggregate_user_state(
        logs, PROBLEMS, user_id="u", target_exam="CPA_1",
        days_until_exam=90, available_hours_per_day=8, current_stage="objective_entry",
    )
    # UNKNOWN은 무시되고 P-A1만 누적
    assert len(us["subject_states"]) == 1
    assert us["subject_states"][0]["accuracy"] == 1.0


# ---------- concept_mastery ----------

PROBLEMS_WITH_CONCEPTS = [
    {
        "problem_id": "P-FA1",
        "subject": "accounting",
        "concept_tags": ["재무회계: 금융자산", "amortized_cost", "effective_interest_rate"],
        "time_strategy": {"target_seconds": 90, "skip_threshold_seconds": 120, "exam_room_rule": ""},
    },
    {
        "problem_id": "P-FA2",
        "subject": "accounting",
        "concept_tags": ["재무회계: 금융자산", "impairment_loss"],
        "time_strategy": {"target_seconds": 90, "skip_threshold_seconds": 120, "exam_room_rule": ""},
    },
    {
        "problem_id": "P-RV1",
        "subject": "accounting",
        "concept_tags": ["재무회계: 수익인식", "revenue_recognition"],
        "time_strategy": {"target_seconds": 100, "skip_threshold_seconds": 130, "exam_room_rule": ""},
    },
    {
        "problem_id": "P-NOTAG",
        "subject": "accounting",
        "concept_tags": ["amortized_cost"],  # Korean prefix 없음 → 집계 제외
        "time_strategy": {"target_seconds": 90, "skip_threshold_seconds": 120, "exam_room_rule": ""},
    },
]


def test_concept_mastery_aggregates_by_korean_primary_tag():
    pbi = {p["problem_id"]: p for p in PROBLEMS_WITH_CONCEPTS}
    logs = [
        _log("P-FA1", True, 80),
        _log("P-FA1", False, 90),
        _log("P-FA2", False, 100),  # same concept = "재무회계: 금융자산"
        _log("P-RV1", True, 95),
        _log("P-RV1", True, 90),
    ]
    agg = aggregate_subject_state(logs, pbi, "accounting")
    cm = {row["concept"]: row["mastery"] for row in agg["concept_mastery"]}
    # 재무회계: 금융자산 — 3건 중 1건 정답 = 0.3333
    assert cm["재무회계: 금융자산"] == round(1 / 3, 4)
    # 재무회계: 수익인식 — 2건 모두 정답
    assert cm["재무회계: 수익인식"] == 1.0


def test_concept_mastery_ignores_problems_without_korean_tag():
    pbi = {p["problem_id"]: p for p in PROBLEMS_WITH_CONCEPTS}
    logs = [_log("P-NOTAG", True, 80), _log("P-NOTAG", False, 90)]
    agg = aggregate_subject_state(logs, pbi, "accounting")
    # 한국어 primary tag가 없으면 concept_mastery에서 누락
    assert "concept_mastery" not in agg


def test_concept_mastery_sorted_weakness_first():
    pbi = {p["problem_id"]: p for p in PROBLEMS_WITH_CONCEPTS}
    logs = [
        _log("P-FA1", False, 80),  # 금융자산 0% (1건)
        _log("P-RV1", True, 80),   # 수익인식 100%
    ]
    agg = aggregate_subject_state(logs, pbi, "accounting")
    cm = agg["concept_mastery"]
    # 약점 우선: 금융자산(0) 먼저, 수익인식(1.0) 나중
    assert cm[0]["concept"] == "재무회계: 금융자산"
    assert cm[-1]["concept"] == "재무회계: 수익인식"


# ---------- inferred risk_tags ----------

def test_risk_tags_inferred_time_pressure_when_overrun_high():
    pbi = {p["problem_id"]: p for p in PROBLEMS}
    # 4건 모두 시간초과 + 명시 태그 없음 → time_pressure 자동 추가
    logs = [
        _log("P-A1", True, 150),
        _log("P-A1", False, 150),
        _log("P-A2", True, 140),
        _log("P-A2", False, 140),
    ]
    agg = aggregate_subject_state(logs, pbi, "accounting")
    assert "time_pressure" in agg["risk_tags"]


def test_risk_tags_inferred_concept_gap_when_low_mastery():
    pbi = {p["problem_id"]: p for p in PROBLEMS_WITH_CONCEPTS}
    # 금융자산 0% mastery — concept_gap 자동 추가
    logs = [_log("P-FA1", False, 80), _log("P-FA1", False, 90)]
    agg = aggregate_subject_state(logs, pbi, "accounting")
    assert "concept_gap" in agg["risk_tags"]


def test_explicit_mistake_categories_take_priority():
    pbi = {p["problem_id"]: p for p in PROBLEMS}
    # 4건 모두 시간초과 + 명시 태그 3개 → 명시가 슬롯 다 차지, 추론 안 들어옴
    logs = [
        _log("P-A1", False, 150, mistakes=["concept_gap", "memory_decay", "fact_error"]),
    ]
    agg = aggregate_subject_state(logs, pbi, "accounting")
    # 상한 3개, 모두 명시 태그
    assert len(agg["risk_tags"]) == 3
    assert set(agg["risk_tags"]) == {"concept_gap", "memory_decay", "fact_error"}
    # time_pressure는 슬롯이 꽉 차서 들어오지 못한다
    assert "time_pressure" not in agg["risk_tags"]


# ---------- infer_current_stage ----------

def test_infer_stage_intro_when_no_logs():
    assert infer_current_stage([]) == "intro"


def test_infer_stage_post_lecture_when_few_logs():
    logs = [_log("P-A1", True, 80) for _ in range(10)]
    assert infer_current_stage(logs) == "post_lecture"


def test_infer_stage_objective_entry_when_low_accuracy():
    # 100건 풀었지만 정답률 40% — 단계 도약 막힘
    logs = [_log("P-A1", True, 80) for _ in range(40)] + [
        _log("P-A1", False, 80) for _ in range(60)
    ]
    assert infer_current_stage(logs) == "objective_entry"


def test_infer_stage_past_exam_rotation_when_moderate_volume():
    logs = [_log("P-A1", True, 80) for _ in range(80)] + [
        _log("P-A1", False, 80) for _ in range(40)
    ]
    # n=120 (≥80, <200), accuracy=0.667
    assert infer_current_stage(logs) == "past_exam_rotation"


def test_infer_stage_mock_exam_when_high_volume_good_accuracy():
    # n=250 (≥200, <400), accuracy=0.7 (≥0.62)
    logs = [_log("P-A1", True, 80) for _ in range(175)] + [
        _log("P-A1", False, 80) for _ in range(75)
    ]
    assert infer_current_stage(logs) == "mock_exam"


def test_infer_stage_final_when_volume_and_accuracy_meet_bar():
    # n=500 (≥400), accuracy=0.8 (≥0.72)
    logs = [_log("P-A1", True, 80) for _ in range(400)] + [
        _log("P-A1", False, 80) for _ in range(100)
    ]
    assert infer_current_stage(logs) == "final"


def test_aggregate_user_state_uses_inferred_stage_when_none():
    logs = [_log("P-A1", True, 80) for _ in range(5)]
    us = aggregate_user_state(
        logs, PROBLEMS, user_id="u", target_exam="CPA_1",
        days_until_exam=90, available_hours_per_day=8, current_stage=None,
    )
    # 5건만 누적 → post_lecture
    assert us["current_stage"] == "post_lecture"


def test_aggregate_user_state_respects_explicit_stage():
    logs = [_log("P-A1", True, 80) for _ in range(5)]
    # 5건만 누적이지만 사용자가 final 명시 → 추정으로 덮어쓰지 않음
    us = aggregate_user_state(
        logs, PROBLEMS, user_id="u", target_exam="CPA_1",
        days_until_exam=90, available_hours_per_day=8, current_stage="final",
    )
    assert us["current_stage"] == "final"
