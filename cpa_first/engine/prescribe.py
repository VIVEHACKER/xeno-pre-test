"""결정론적 처방 엔진.

입력 UserState와 DecisionRule 목록을 받아 Prescription을 산출한다.
동일 입력은 동일 출력을 보장하고, 모든 처방 항목에 evidence_refs를 첨부한다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


# risk_score 산출용 임계값. PRD §4.6의 누적 항목을 자동화 가능한 신호로 옮긴 것.
FAIL_RISK_ACCURACY = 0.40
TIME_OVERRUN_THRESHOLD = 0.30
CONCEPT_GAP_THRESHOLD = 0.50
DEADLINE_TIGHT_DAYS = 30
DEADLINE_NEAR_DAYS = 60


def _user_subjects(user_state: dict) -> set[str]:
    return {s["subject"] for s in user_state.get("subject_states", [])}


def _user_risk_tags(user_state: dict) -> set[str]:
    tags: set[str] = set()
    for state in user_state.get("subject_states", []):
        tags.update(state.get("risk_tags", []))
    return tags


def _matches_stage(rule: dict, user_state: dict) -> bool:
    stages = rule.get("applicable_stages") or []
    if not stages:
        return True
    return user_state["current_stage"] in stages


def _matches_subjects(rule: dict, user_state: dict) -> bool:
    rule_subjects = rule.get("applicable_subjects") or []
    if not rule_subjects:
        return True
    user_subjects = _user_subjects(user_state)
    for rs in rule_subjects:
        if rs == "general":
            return True
        if rs == "accounting_tax":
            if "accounting" in user_subjects and "tax" in user_subjects:
                return True
        elif rs in user_subjects:
            return True
    return False


def _matches_risk_tags(rule: dict, user_state: dict) -> bool:
    required = rule.get("required_risk_tags") or []
    if not required:
        return True
    user_tags = _user_risk_tags(user_state)
    return any(tag in user_tags for tag in required)


def _matches(rule: dict, user_state: dict) -> bool:
    return (
        _matches_stage(rule, user_state)
        and _matches_subjects(rule, user_state)
        and _matches_risk_tags(rule, user_state)
    )


def _task_subject(rule: dict, user_state: dict) -> str:
    rule_subjects = rule.get("applicable_subjects") or []
    user_subjects = _user_subjects(user_state)
    matched = [s for s in rule_subjects if s in user_subjects]
    if matched == ["accounting"]:
        return "accounting"
    if matched == ["tax"]:
        return "tax"
    return "mixed"


def _estimated_minutes(rule: dict) -> int:
    count = int(rule.get("source_signal_count", 0))
    if count >= 10:
        return 60
    if count >= 3:
        return 45
    return 30


def _risk_score(user_state: dict, matched: list[dict]) -> tuple[int, list[str]]:
    """PRD §4.6 누적 risk_score. 0~100 clamp.

    자동화 가능한 신호만 사용. 계획 수행률/점수 정체는 풀이 로그 누적 후 M3에서 추가.
    """
    score = 0
    drivers: list[str] = []
    days = int(user_state["days_until_exam"])

    for state in user_state.get("subject_states", []):
        if state["accuracy"] < FAIL_RISK_ACCURACY:
            score += 20
            drivers.append(f"{state['subject']} 과락 위험(accuracy<{FAIL_RISK_ACCURACY})")
        if state["time_overrun_rate"] > TIME_OVERRUN_THRESHOLD:
            score += 15
            drivers.append(f"{state['subject']} 시간 초과 위험")
        concept_mastery = state.get("concept_mastery") or []
        if concept_mastery:
            avg_mastery = sum(c["mastery"] for c in concept_mastery) / len(concept_mastery)
            if avg_mastery < CONCEPT_GAP_THRESHOLD:
                score += 15
                drivers.append(f"{state['subject']} 핵심 개념 공백")

    if days < DEADLINE_TIGHT_DAYS:
        score += 25
        drivers.append(f"잔여 {days}일 — 압축 구간")
    elif days < DEADLINE_NEAR_DAYS:
        score += 10
        drivers.append(f"잔여 {days}일 — 마감 임박")

    if len(matched) >= 5:
        score += 20
        drivers.append("다수 규칙 동시 발동")
    elif len(matched) >= 3:
        score += 10
        drivers.append("복수 규칙 동시 발동")

    return min(score, 100), drivers


def _diagnosis(user_state: dict, matched: list[dict]) -> dict:
    days = int(user_state["days_until_exam"])
    score, score_drivers = _risk_score(user_state, matched)

    if score >= 50:
        risk_level = "high"
    elif score >= 25:
        risk_level = "moderate"
    else:
        risk_level = "low"

    if matched:
        focus = ", ".join(r["rule_name"] for r in matched)
        summary = (
            f"단계 {user_state['current_stage']}에서 매칭된 신호: {focus}. "
            f"잔여 {days}일, 리스크 점수 {score}/100."
        )
    else:
        summary = (
            f"단계 {user_state['current_stage']}에서 매칭되는 규칙이 없다. "
            f"리스크 점수 {score}/100. 풀이 로그 보강으로 진단 정밀도를 높여야 한다."
        )

    drivers: list[str] = list(score_drivers)
    drivers.extend(r["rule_name"] for r in matched)
    drivers.extend(sorted(_user_risk_tags(user_state)))
    deduped = list(dict.fromkeys(drivers))

    return {
        "summary": summary,
        "risk_level": risk_level,
        "risk_drivers": deduped,
    }


def _weekly_goal(matched: list[dict], user_state: dict) -> dict:
    if matched:
        top = matched[0]
        return {
            "goal_text": top["action_text"],
            "verification_metric": (
                f"주간 처방 수행률 80% 이상, 매칭 규칙 {top['rule_key']} 관련 약점 지표 측정"
            ),
        }
    return {
        "goal_text": (
            "이번 주는 진단 보강에 집중한다. 풀이 로그를 충분히 남겨 다음 처방 매칭이 가능하게 한다."
        ),
        "verification_metric": "풀이 로그 50건 이상 누적, 모든 풀이에 mistake_categories 입력",
    }


def _daily_tasks(matched: list[dict], user_state: dict) -> list[dict]:
    if not matched:
        return [
            {
                "task_text": "오늘은 풀이 로그를 30건 이상 남기고, 각 풀이의 오답 원인을 분류한다.",
                "subject": "mixed",
                "estimated_minutes": 60,
            }
        ]
    return [
        {
            "task_text": rule["action_text"],
            "subject": _task_subject(rule, user_state),
            "estimated_minutes": _estimated_minutes(rule),
        }
        for rule in matched
    ]


def _concept_frequency(problem_intel: list[dict]) -> dict[str, int]:
    """problem_intelligence 시드에서 각 concept_tag의 출제 빈도를 집계."""
    freq: dict[str, int] = {}
    for problem in problem_intel:
        for tag in problem.get("concept_tags") or []:
            freq[tag] = freq.get(tag, 0) + 1
    return freq


def _importance_score(
    concept: str,
    mastery: float,
    frequency: int,
    max_frequency: int,
) -> float:
    """PRD §4.5의 가중합을 자동화 가능한 신호만으로 축소.

    importance = 사용자 약점도(0.6) + 출제 빈도(0.4)
    원안의 최근 출제성/배점/변형 가능성/합격수기 강조도는 시드 보강 후 도입.
    """
    weakness = 1.0 - max(0.0, min(1.0, mastery))
    freq_ratio = (frequency / max_frequency) if max_frequency > 0 else 0.0
    return round(weakness * 0.6 + freq_ratio * 0.4, 4)


def _concepts_to_review(
    user_state: dict,
    problem_intel: list[dict] | None = None,
    n: int = 3,
) -> list[str]:
    freq = _concept_frequency(problem_intel or [])
    max_freq = max(freq.values()) if freq else 0

    candidates: list[tuple[float, str, str]] = []
    for state in user_state.get("subject_states", []):
        for cm in state.get("concept_mastery") or []:
            concept = str(cm["concept"])
            mastery = float(cm["mastery"])
            # concept 이름이 problem_intelligence의 어떤 concept_tag에 부분 매칭되는지 확인
            matched_freq = max(
                (freq[tag] for tag in freq if tag in concept or concept in tag),
                default=0,
            )
            score = _importance_score(concept, mastery, matched_freq, max_freq)
            candidates.append((-score, concept, state["subject"]))
    # 결정론: score desc, concept asc, subject asc
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    seen: set[str] = set()
    ordered: list[str] = []
    for _, concept, _subject in candidates:
        if concept not in seen:
            seen.add(concept)
            ordered.append(concept)
    return ordered[:n]


def _evidence_refs(matched: list[dict], user_state: dict) -> list[dict]:
    refs: list[dict] = [
        {
            "ref_type": "user_state",
            "ref_id": user_state["user_id"],
            "note": (
                f"stage={user_state['current_stage']}, "
                f"days_until_exam={user_state['days_until_exam']}"
            ),
        }
    ]
    for rule in matched:
        refs.append(
            {
                "ref_type": "decision_rule",
                "ref_id": rule["rule_key"],
                "note": rule["rule_name"],
            }
        )
    return refs


def _prescription_id(user_state: dict, matched: list[dict]) -> str:
    payload = json.dumps(
        {
            "user_id": user_state["user_id"],
            "stage": user_state["current_stage"],
            "rule_keys": sorted(r["rule_key"] for r in matched),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"rx-{user_state['user_id']}-{digest}"


def prescribe(
    user_state: dict,
    decision_rules: list[dict],
    *,
    generated_at: str,
    problem_intel: list[dict] | None = None,
) -> dict:
    matched = [r for r in decision_rules if _matches(r, user_state)]
    matched.sort(key=lambda r: (-float(r.get("confidence", 0)), r["rule_key"]))

    return {
        "prescription_id": _prescription_id(user_state, matched),
        "user_id": user_state["user_id"],
        "generated_at": generated_at,
        "diagnosis": _diagnosis(user_state, matched),
        "weekly_goal": _weekly_goal(matched, user_state),
        "daily_tasks": _daily_tasks(matched, user_state),
        "concepts_to_review": _concepts_to_review(user_state, problem_intel),
        "problems_to_solve": [],
        "problems_to_skip": [],
        "triggered_rule_keys": [r["rule_key"] for r in matched],
        "evidence_refs": _evidence_refs(matched, user_state),
    }


def load_problem_intelligence(directory: Path) -> list[dict]:
    items: list[dict] = []
    for path in sorted(directory.glob("*.problem_intelligence.json")):
        with path.open("r", encoding="utf-8") as f:
            items.append(json.load(f))
    return items


def load_decision_rules(directory: Path) -> list[dict]:
    rules: list[dict] = []
    for path in sorted(directory.glob("*.decision_rule.json")):
        with path.open("r", encoding="utf-8") as f:
            rules.append(json.load(f))
    return rules


def load_user_state(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
