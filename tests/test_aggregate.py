"""aggregate.py — MistakeLog → UserState 산출 단위 테스트."""

from __future__ import annotations

from cpa_first.engine import aggregate_subject_state, aggregate_user_state


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
