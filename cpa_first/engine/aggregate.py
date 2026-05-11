"""풀이 로그(MistakeLog) 누적 → UserState 자동 산출.

M5 학습 루프의 코어. 사용자가 풀이 로그를 충분히 남기면
다음 진단을 손으로 입력하지 않아도 user_state가 자동으로 만들어진다.

설계:
- 정답률: 과목별 correct=True 비율
- 시간 초과율: problem_intelligence.time_strategy.skip_threshold_seconds 초과 비율
- risk_tags: 누적된 mistake_categories를 빈도 내림차순으로 상위 3개
"""

from __future__ import annotations

from typing import Any


def _problems_by_id(problems: list[dict]) -> dict[str, dict]:
    return {p["problem_id"]: p for p in problems}


def aggregate_subject_state(
    logs: list[dict],
    problems_by_id: dict[str, dict],
    subject: str,
) -> dict[str, Any] | None:
    """해당 과목 로그가 0건이면 None 반환."""
    if not logs:
        return None

    correct = sum(1 for log in logs if log.get("correct"))
    accuracy = correct / len(logs)

    overruns = 0
    with_threshold = 0
    risk_counts: dict[str, int] = {}

    for log in logs:
        problem = problems_by_id.get(log["problem_id"])
        if problem and "time_strategy" in problem:
            threshold = problem["time_strategy"]["skip_threshold_seconds"]
            with_threshold += 1
            if log.get("time_seconds", 0) > threshold:
                overruns += 1
        for cat in log.get("mistake_categories") or []:
            risk_counts[cat] = risk_counts.get(cat, 0) + 1

    time_overrun_rate = overruns / with_threshold if with_threshold else 0.0
    # 결정론: 빈도 내림차순, 동률 시 키 알파벳 오름차순
    risk_tags = sorted(risk_counts, key=lambda k: (-risk_counts[k], k))[:3]

    return {
        "subject": subject,
        "accuracy": round(accuracy, 4),
        "time_overrun_rate": round(time_overrun_rate, 4),
        "risk_tags": risk_tags,
    }


def aggregate_user_state(
    logs: list[dict],
    problems: list[dict],
    *,
    user_id: str,
    target_exam: str,
    days_until_exam: int,
    available_hours_per_day: float,
    current_stage: str,
) -> dict[str, Any]:
    """누적 로그 + 환경 컨텍스트 → user_state.schema.json 호환 dict."""
    pbi = _problems_by_id(problems)

    # 과목별 분리
    by_subject: dict[str, list[dict]] = {}
    for log in logs:
        problem = pbi.get(log["problem_id"])
        subject = problem.get("subject") if problem else None
        if subject in {"accounting", "tax"}:
            by_subject.setdefault(subject, []).append(log)

    subject_states: list[dict[str, Any]] = []
    # 결정론: 과목 알파벳 순
    for subject in sorted(by_subject):
        agg = aggregate_subject_state(by_subject[subject], pbi, subject)
        if agg is not None:
            subject_states.append(agg)

    return {
        "user_id": user_id,
        "target_exam": target_exam,
        "days_until_exam": days_until_exam,
        "available_hours_per_day": available_hours_per_day,
        "current_stage": current_stage,
        "subject_states": subject_states,
    }
