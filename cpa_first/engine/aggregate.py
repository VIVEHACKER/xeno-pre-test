"""풀이 로그(MistakeLog) 누적 → UserState 자동 산출.

M5 학습 루프의 코어. 사용자가 풀이 로그를 충분히 남기면
다음 진단을 손으로 입력하지 않아도 user_state가 자동으로 만들어진다.

설계:
- 정답률: 과목별 correct=True 비율
- 시간 초과율: problem_intelligence.time_strategy.skip_threshold_seconds 초과 비율
- risk_tags: 누적된 mistake_categories를 빈도 내림차순으로 상위 3개
  + 행동 신호 보강: 시간초과율 0.3↑ → time_pressure, mastery<0.4 개념 존재 → concept_gap
- concept_mastery: problem.concept_tags의 첫 Korean tag(':' 포함)를 concept key로
  사용해 과목별로 correct/total 누적. 약점 우선(오름차순) 결정론 정렬.
- current_stage: 명시 제공 시 그대로, None이면 log 분량+정답률로 자동 추정.
"""

from __future__ import annotations

from typing import Any, Iterable

from cpa_first.subjects import is_known_subject


# 행동 신호 임계값. 변경 시 영향: stage 추정 + 추론 risk_tag.
TIME_OVERRUN_RISK_THRESHOLD = 0.30
LOW_MASTERY_THRESHOLD = 0.40
RISK_TAG_LIMIT = 3


def _problems_by_id(problems: list[dict]) -> dict[str, dict]:
    return {p["problem_id"]: p for p in problems}


def _primary_concept(problem: dict) -> str | None:
    """problem.concept_tags 중 첫 Korean tag(':' 포함)를 concept key로 채택.

    매핑이 일관되도록 한국어 우선 (영문 태그는 키워드성). 없으면 None.
    """
    for tag in problem.get("concept_tags") or []:
        if isinstance(tag, str) and ":" in tag:
            return tag
    return None


def _aggregate_concept_mastery(
    logs: list[dict],
    problems_by_id: dict[str, dict],
) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, int]] = {}
    for log in logs:
        problem = problems_by_id.get(log["problem_id"])
        if not problem:
            continue
        concept = _primary_concept(problem)
        if not concept:
            continue
        bucket = counts.setdefault(concept, {"correct": 0, "total": 0})
        bucket["total"] += 1
        if log.get("correct"):
            bucket["correct"] += 1
    # 약점 우선(오름차순), 동률 시 concept 알파벳 오름차순
    return sorted(
        (
            {"concept": concept, "mastery": round(b["correct"] / b["total"], 4)}
            for concept, b in counts.items()
        ),
        key=lambda x: (x["mastery"], x["concept"]),
    )


def _combine_risk_tags(
    explicit_counts: dict[str, int],
    time_overrun_rate: float,
    concept_mastery: list[dict[str, Any]],
) -> list[str]:
    """명시 mistake_categories를 우선하고 행동 신호로 보강.

    탑3 상한. 행동 신호는 명시 태그가 채우지 못한 빈 슬롯만 채운다 — 사용자 진단을 덮어쓰지 않는다.
    """
    explicit = sorted(explicit_counts, key=lambda k: (-explicit_counts[k], k))
    selected: list[str] = list(explicit[:RISK_TAG_LIMIT])

    inferred: list[str] = []
    if time_overrun_rate >= TIME_OVERRUN_RISK_THRESHOLD:
        inferred.append("time_pressure")
    if any(cm["mastery"] < LOW_MASTERY_THRESHOLD for cm in concept_mastery):
        inferred.append("concept_gap")

    for tag in inferred:
        if len(selected) >= RISK_TAG_LIMIT:
            break
        if tag not in selected:
            selected.append(tag)
    return selected


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
    explicit_counts: dict[str, int] = {}

    for log in logs:
        problem = problems_by_id.get(log["problem_id"])
        if problem and "time_strategy" in problem:
            threshold = problem["time_strategy"]["skip_threshold_seconds"]
            with_threshold += 1
            if log.get("time_seconds", 0) > threshold:
                overruns += 1
        for cat in log.get("mistake_categories") or []:
            explicit_counts[cat] = explicit_counts.get(cat, 0) + 1

    time_overrun_rate = overruns / with_threshold if with_threshold else 0.0
    concept_mastery = _aggregate_concept_mastery(logs, problems_by_id)
    risk_tags = _combine_risk_tags(explicit_counts, time_overrun_rate, concept_mastery)

    state: dict[str, Any] = {
        "subject": subject,
        "accuracy": round(accuracy, 4),
        "time_overrun_rate": round(time_overrun_rate, 4),
        "risk_tags": risk_tags,
    }
    if concept_mastery:
        state["concept_mastery"] = concept_mastery
    return state


def infer_current_stage(logs: Iterable[dict]) -> str:
    """log 분량 + 정답률로 학습 단계를 자동 추정.

    경계는 user_state schema enum: intro → post_lecture → objective_entry
    → past_exam_rotation → mock_exam → final. 분량과 정답률을 AND로 묶지 않고
    "둘 중 약한 쪽이 단계를 결정한다"는 방향으로 잡았다(상위 단계 도약 방지).
    """
    logs_list = list(logs)
    n = len(logs_list)
    if n == 0:
        return "intro"
    correct = sum(1 for log in logs_list if log.get("correct"))
    accuracy = correct / n

    if n < 30:
        return "post_lecture"
    if n < 80 or accuracy < 0.50:
        return "objective_entry"
    if n < 200 or accuracy < 0.62:
        return "past_exam_rotation"
    if n < 400 or accuracy < 0.72:
        return "mock_exam"
    return "final"


def aggregate_user_state(
    logs: list[dict],
    problems: list[dict],
    *,
    user_id: str,
    target_exam: str,
    days_until_exam: int,
    available_hours_per_day: float,
    current_stage: str | None = None,
) -> dict[str, Any]:
    """누적 로그 + 환경 컨텍스트 → user_state.schema.json 호환 dict.

    current_stage=None이면 logs 행동 신호로 자동 추정.
    """
    pbi = _problems_by_id(problems)

    # 과목별 분리. 등록된 과목만 누적 (알 수 없는 과목은 무시).
    by_subject: dict[str, list[dict]] = {}
    for log in logs:
        problem = pbi.get(log["problem_id"])
        subject = problem.get("subject") if problem else None
        if subject and is_known_subject(subject):
            by_subject.setdefault(subject, []).append(log)

    subject_states: list[dict[str, Any]] = []
    # 결정론: 과목 알파벳 순
    for subject in sorted(by_subject):
        agg = aggregate_subject_state(by_subject[subject], pbi, subject)
        if agg is not None:
            subject_states.append(agg)

    resolved_stage = current_stage if current_stage is not None else infer_current_stage(logs)

    return {
        "user_id": user_id,
        "target_exam": target_exam,
        "days_until_exam": days_until_exam,
        "available_hours_per_day": available_hours_per_day,
        "current_stage": resolved_stage,
        "subject_states": subject_states,
    }
