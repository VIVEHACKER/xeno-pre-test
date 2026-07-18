"""D-day 기반 다주차 학습 로드맵 생성기.

aggregate.py가 산출한 user_state를 받아 시험일까지의 주차별 학습 계획을 만든다.
prescribe.py가 "이번 주" 처방이라면, 이 모듈은 시험일까지의 전체 항로를 제시한다.

설계:
- total_weeks = min(max_weeks, ceil(days_until_exam / 7)), 최소 1주
- 단계 진행: current_stage부터 STAGE_ORDER를 따라 잔여 주를 배분한다.
  잔여 주 < 잔여 단계 수면 시험에 가까운 뒤 단계를 우선 보존(압축)하고,
  충분하면 STAGE_WEEK_WEIGHTS 비례로 배분한다(단계당 최소 1주).
- subject_allocation: 약점 가중 — accuracy가 낮을수록 많은 시간.
  과락 위험(accuracy < 0.40) 과목은 주당 최소 비율(floor)을 보장하고,
  안정 과목(accuracy >= 0.70)은 망각 방지 유지 시간만 배정한다.
- 마지막 주는 항상 모의/최종 점검 + 과락 방어 체크 milestone.
- subject_states가 비면 진단 보강 1주 플랜으로 폴백한다.
- 결정론: 동일 입력 → 동일 출력 (현재 시각/난수 미사용).
"""

from __future__ import annotations

import math

from cpa_first.subjects import name_ko

# 학습 단계 진행 순서. user_state.current_stage enum과 동일해야 한다.
STAGE_ORDER: tuple[str, ...] = (
    "intro",
    "post_lecture",
    "objective_entry",
    "past_exam_rotation",
    "mock_exam",
    "final",
)

# 잔여 주가 단계 수보다 많을 때의 비례 배분 가중치. 기출 회독에 가장 큰 비중.
STAGE_WEEK_WEIGHTS: dict[str, float] = {
    "intro": 1.0,
    "post_lecture": 2.0,
    "objective_entry": 3.0,
    "past_exam_rotation": 4.0,
    "mock_exam": 2.0,
    "final": 1.0,
}

STAGE_NAMES_KO: dict[str, str] = {
    "intro": "입문",
    "post_lecture": "강의 복습",
    "objective_entry": "객관식 진입",
    "past_exam_rotation": "기출 회독",
    "mock_exam": "모의고사",
    "final": "파이널",
}

STAGE_THEMES: dict[str, str] = {
    "intro": "기초 개념 정착",
    "post_lecture": "강의 복습과 기본 문제 정착",
    "objective_entry": "객관식 유형 진입 훈련",
    "past_exam_rotation": "기출 회독과 약점 보강",
    "mock_exam": "모의고사 실전 감각 훈련",
    "final": "최종 정리와 과락 방어",
}

STAGE_MILESTONES: dict[str, str] = {
    "intro": "입문 범위 1회독 완료",
    "post_lecture": "수강 단원 복습과 기본문제 풀이 완료",
    "objective_entry": "객관식 유형별 문제 세트 풀이 완료",
    "past_exam_rotation": "기출 1개년 회독과 오답 분석 완료",
    "mock_exam": "전 과목 모의고사 1회 응시와 오답 분석 완료",
    "final": "전 범위 핵심 요약 점검 완료",
}

# 모든 주에 측정 가능한 검증 지표를 붙인다 (PRD 검증 가능성 원칙).
STAGE_METRICS: dict[str, str] = {
    "intro": "입문 단원 확인 문제 정답률 60% 이상",
    "post_lecture": "복습 단원 기본문제 정답률 70% 이상",
    "objective_entry": "객관식 세트 정답률 55% 이상, 문항당 평균 풀이 시간 기록",
    "past_exam_rotation": "기출 1회분 정답률 60% 이상, 시간 초과율 30% 이하",
    "mock_exam": "모의고사 전 과목 평균 60% 이상, 매 과목 40% 이상",
    "final": "최종 점검 모의고사 평균 60% 이상 AND 매 과목 40% 이상",
}

# CPA 1차 합격 기준: 전 과목 평균 60% 이상 AND 매 과목 40% 이상(과락).
PASS_AVERAGE = 0.60
PASS_SUBJECT_FLOOR = 0.40

# 플랜 지평 상한. 1년(52주) 완주 로드맵을 표현할 수 있어야 한다 —
# 과거 16주 상한은 D-365 입력을 조용히 절단해 "1년 플랜" 자체가 불가능했다.
DEFAULT_MAX_WEEKS = 52

# 합격 필요 총 학습시간 추정(시간). 통상 수험 통계 3,000~5,000h 범위의 보수적
# 중앙 추정 — 정밀 통계가 아니므로 feasibility 노트에 가정임을 명시한다.
TOTAL_REQUIRED_HOURS = 3500

# feasibility 판정 임계값: planned/required 비율.
FEASIBILITY_TIGHT_RATIO = 0.70

# 튜토리얼(교습 콘텐츠)을 배정하는 단계.
TEACHING_STAGES = frozenset({"intro", "post_lecture", "objective_entry"})

# 과목 시간 배분 임계값. FAIL_RISK_ACCURACY는 prescribe.py와 동일 기준.
FAIL_RISK_ACCURACY = 0.40
STABLE_ACCURACY = 0.70
MAINTENANCE_RATIO = 0.05  # 망각 방지: 모든 과목에 주당 최소 5% 시간
FAIL_RISK_FLOOR_RATIO = 0.15  # 과락 위험 과목은 주당 최소 15% 시간 보장
FAIL_RISK_WEIGHT_BOOST = 0.5  # 과락 위험 과목 약점 가중 부스트

FINAL_WEEK_MILESTONE = "모의/최종 점검 — 전 과목 평균 60% 이상 및 매 과목 40% 이상(과락 방어) 확인"
FINAL_WEEK_METRIC = "최종 점검 모의고사에서 전 과목 평균 60% 이상 AND 매 과목 40% 이상 득점"

# 진단 데이터가 없을 때 균등 배정할 CPA 1차 과목 (user_state 스키마 enum과 동일).
FALLBACK_SUBJECTS: tuple[str, ...] = (
    "accounting",
    "tax",
    "business",
    "corporate_law",
    "economics",
)


def _total_weeks(days_until_exam: int, max_weeks: int) -> int:
    """플랜 주차 수. 최소 1주, max_weeks 상한."""
    return max(1, min(max_weeks, math.ceil(max(0, days_until_exam) / 7)))


def _days_range(days_until_exam: int, week_no: int) -> str:
    """주차의 D-day 구간 문자열. 예: D-84~D-78."""
    start = max(days_until_exam - 7 * (week_no - 1), 0)
    end = max(start - 6, 0)
    return f"D-{start}~D-{end}"


def _remaining_stages(current_stage: str) -> list[str]:
    """current_stage부터 시험까지의 단계 목록. 알 수 없는 단계면 처음부터(보수적)."""
    idx = STAGE_ORDER.index(current_stage) if current_stage in STAGE_ORDER else 0
    return list(STAGE_ORDER[idx:])


def _distribute_stage_weeks(stages: list[str], total_weeks: int) -> list[tuple[str, int]]:
    """잔여 주를 단계별로 배분.

    - 잔여 주 ≤ 단계 수: 시험에 가까운 뒤 단계를 우선 보존(앞 단계부터 압축 제거)
    - 잔여 주 > 단계 수: 단계당 최소 1주 + 초과분을 STAGE_WEEK_WEIGHTS 비례 배분.
      나머지 주는 소수부 큰 순서, 동률이면 뒤 단계 우선 — 결정론 보장.
    """
    if total_weeks <= len(stages):
        kept = stages[len(stages) - total_weeks :]
        return [(stage, 1) for stage in kept]

    extra = total_weeks - len(stages)
    weights = [STAGE_WEEK_WEIGHTS[stage] for stage in stages]
    total_weight = sum(weights)
    raw = [extra * w / total_weight for w in weights]
    counts = [1 + int(r) for r in raw]
    remainder = total_weeks - sum(counts)
    order = sorted(range(len(stages)), key=lambda i: (-(raw[i] - int(raw[i])), -i))
    for i in order[:remainder]:
        counts[i] += 1
    return list(zip(stages, counts, strict=True))


def _subject_weight(accuracy: float) -> float:
    """약점 가중치. 안정 과목은 0(유지 시간만), 과락 위험은 부스트."""
    if accuracy >= STABLE_ACCURACY:
        return 0.0
    weight = 1.0 - accuracy
    if accuracy < FAIL_RISK_ACCURACY:
        weight += FAIL_RISK_WEIGHT_BOOST
    return weight


def _allocation_reason(subject: str, accuracy: float) -> str:
    pct = round(accuracy * 100)
    if accuracy < FAIL_RISK_ACCURACY:
        return (
            f"{name_ko(subject)} 정답률 {pct}% — 과락선(40%) 미달이라 집중 보강 가중을 적용하고 "
            f"주당 최소 {round(FAIL_RISK_FLOOR_RATIO * 100)}% 시간을 보장한다."
        )
    if accuracy >= STABLE_ACCURACY:
        return f"{name_ko(subject)} 정답률 {pct}% — 안정 과목이라 망각 방지 유지 시간만 배정한다."
    return (
        f"{name_ko(subject)} 정답률 {pct}% — 약점 가중 배분으로 정답률이 낮을수록 "
        f"시간을 더 배정한다."
    )


def _allocate_subject_hours(subject_states: list[dict], hours_per_week: float) -> list[dict]:
    """주간 시간을 과목별로 배분. 합계는 hours_per_week와 일치한다.

    1) 전 과목 망각 방지 유지 시간(MAINTENANCE_RATIO) 선배정
    2) 잔여 풀을 약점 가중치 비례 배분 (안정 과목 가중 0)
    3) 과락 위험 과목 floor 보장 — 초과분은 비-과락 과목 가변분에서 비례 차감
    4) 반올림 잔차는 최대 배정 과목에 흡수 (결정론)
    """
    n = len(subject_states)
    if hours_per_week <= 0:
        return [
            {
                "subject": state["subject"],
                "hours": 0.0,
                "reason": "가용 학습 시간이 0이라 배정할 수 없다 — available_hours_per_day 입력이 필요하다.",
            }
            for state in subject_states
        ]

    maintenance = hours_per_week * MAINTENANCE_RATIO
    pool = hours_per_week - maintenance * n
    if pool < 0:
        maintenance = hours_per_week / n
        pool = 0.0

    weights = [_subject_weight(float(state["accuracy"])) for state in subject_states]
    total_weight = sum(weights)
    if total_weight <= 0:
        hours = [maintenance + pool / n for _ in range(n)]
    else:
        hours = [maintenance + pool * w / total_weight for w in weights]

    floor_hours = hours_per_week * FAIL_RISK_FLOOR_RATIO
    fail_idx = {
        i for i, state in enumerate(subject_states) if float(state["accuracy"]) < FAIL_RISK_ACCURACY
    }
    raised = 0.0
    for i in fail_idx:
        if hours[i] < floor_hours:
            raised += floor_hours - hours[i]
            hours[i] = floor_hours
    if raised > 1e-9:
        donors = [i for i in range(n) if i not in fail_idx]
        capacity = sum(max(0.0, hours[i] - maintenance) for i in donors)
        if capacity > 1e-9:
            ratio = min(1.0, raised / capacity)
            for i in donors:
                hours[i] -= max(0.0, hours[i] - maintenance) * ratio

    rounded = [round(h, 2) for h in hours]
    drift = round(hours_per_week - sum(rounded), 2)
    if abs(drift) >= 0.01:
        target = max(range(n), key=lambda i: (rounded[i], -i))
        rounded[target] = round(rounded[target] + drift, 2)

    # 과락 floor 합계가 풀을 초과하는 극단 입력에서 drift 흡수가 음수를 만들 수
    # 있다 — 음수 시간은 무효이므로 0으로 클램프 후 비례 재정규화한다(결정론).
    if any(h < 0 for h in rounded):
        clamped = [max(0.0, h) for h in rounded]
        total = sum(clamped)
        scale = hours_per_week / total if total > 0 else 0.0
        rounded = [round(h * scale, 2) for h in clamped]
        drift = round(hours_per_week - sum(rounded), 2)
        if abs(drift) >= 0.01 and rounded:
            target = max(range(n), key=lambda i: (rounded[i], -i))
            rounded[target] = round(max(0.0, rounded[target] + drift), 2)

    return [
        {
            "subject": state["subject"],
            "hours": rounded[i],
            "reason": _allocation_reason(state["subject"], float(state["accuracy"])),
        }
        for i, state in enumerate(subject_states)
    ]


def _evidence_refs(user_state: dict) -> list[dict]:
    """prescribe.py evidence_refs와 호환되는 근거 추적 참조."""
    refs: list[dict] = [
        {
            "ref_type": "user_state",
            "ref_id": user_state["user_id"],
            "note": (
                f"stage={user_state['current_stage']}, "
                f"days_until_exam={user_state['days_until_exam']}, "
                f"available_hours_per_day={user_state['available_hours_per_day']}"
            ),
        }
    ]
    for state in user_state.get("subject_states", []):
        refs.append(
            {
                "ref_type": "subject_state",
                "ref_id": state["subject"],
                "note": (
                    f"accuracy={state['accuracy']}, "
                    f"time_overrun_rate={state.get('time_overrun_rate', 0)}"
                ),
            }
        )
    refs.append(
        {
            "ref_type": "pass_criteria",
            "ref_id": "CPA_1",
            "note": "전 과목 평균 60% 이상 AND 매 과목 40% 이상(과락 기준)",
        }
    )
    return refs


def _strategy_summary(
    user_state: dict,
    total_weeks: int,
    stage_weeks: list[tuple[str, int]],
) -> str:
    days = int(user_state["days_until_exam"])
    path = " → ".join(f"{STAGE_NAMES_KO[stage]} {count}주" for stage, count in stage_weeks)
    fail_subjects = [
        state["subject"]
        for state in user_state["subject_states"]
        if float(state["accuracy"]) < FAIL_RISK_ACCURACY
    ]
    weak_subjects = [
        state["subject"]
        for state in user_state["subject_states"]
        if FAIL_RISK_ACCURACY <= float(state["accuracy"]) < STABLE_ACCURACY
    ]

    parts = [f"D-{days} 기준 총 {total_weeks}주 로드맵: {path}."]
    if fail_subjects:
        names = ", ".join(name_ko(s) for s in fail_subjects)
        parts.append(
            f"과락 위험 과목({names})은 주당 최소 {round(FAIL_RISK_FLOOR_RATIO * 100)}% "
            f"시간을 보장해 40% 과락선을 방어한다."
        )
    if weak_subjects:
        names = ", ".join(name_ko(s) for s in weak_subjects)
        parts.append(f"약점 과목({names})에 시간을 가중 배정한다.")
    parts.append("합격 기준은 전 과목 평균 60% 이상 AND 매 과목 40% 이상이다.")
    return " ".join(parts)


def _feasibility(current_stage: str, total_weeks: int, hours_per_week: float) -> dict:
    """계획 시간 vs 합격 필요 시간 대조 — '이 계획으로 되는가'에 대한 정직한 답.

    필요 시간은 전체 여정 3,500h(통상 3,000~5,000h 통계의 중앙 추정)에
    잔여 단계 가중치 비율을 곱해 추정한다. 정밀 예측이 아니라 경고 장치다.
    """
    stages = _remaining_stages(current_stage)
    total_weight = sum(STAGE_WEEK_WEIGHTS.values())
    remaining_weight = sum(STAGE_WEEK_WEIGHTS[s] for s in stages)
    required = round(TOTAL_REQUIRED_HOURS * remaining_weight / total_weight)
    planned = round(total_weeks * hours_per_week)
    ratio = planned / required if required > 0 else 0.0

    if ratio >= 1.0:
        verdict = "sufficient"
        note = (
            f"계획 학습시간 {planned}h가 잔여 단계 필요 추정치 {required}h를 충족한다. "
            "페이스 유지 시 시간 관점에서는 합격권 진입이 가능하다."
        )
    elif ratio >= FEASIBILITY_TIGHT_RATIO:
        verdict = "tight"
        note = (
            f"계획 학습시간 {planned}h가 필요 추정치 {required}h의 "
            f"{round(ratio * 100)}%다. 가용 시간을 늘리거나 우선순위 낮은 "
            "범위를 전략적으로 버리는 선택이 필요하다."
        )
    else:
        verdict = "insufficient"
        note = (
            f"계획 학습시간 {planned}h는 필요 추정치 {required}h의 "
            f"{round(ratio * 100)}%에 불과하다 — 이 시간으로는 합격권 도달이 "
            "어렵다. available_hours_per_day 상향 또는 목표 시험 연도 조정을 권한다."
        )
    return {
        "required_hours_estimate": required,
        "planned_hours": planned,
        "ratio": round(ratio, 2),
        "verdict": verdict,
        "note": note,
        "assumption": (
            "전체 여정 필요시간을 3,500h(통상 3,000~5,000h 수험 통계의 중앙 추정)로 두고 "
            "잔여 단계 가중치 비율로 환산한 추정치 — 개인 편차가 크다."
        ),
    }


def _catalog_tutorials_by_subject(content_catalog: dict | None) -> dict[str, list[dict]]:
    """카탈로그 튜토리얼을 엔진 과목 키로 그룹핑. intro 먼저, 그다음 우선순위·ID 순."""
    grouped: dict[str, list[dict]] = {}
    for t in (content_catalog or {}).get("tutorials", []):
        grouped.setdefault(t["subject"], []).append(t)
    for items in grouped.values():
        items.sort(
            key=lambda t: (
                0 if t.get("level") == "intro_low" else 1,
                t.get("priority", 9),
                t["tutorial_id"],
            )
        )
    return grouped


def _assign_week_content(
    weeks: list[dict],
    subject_states: list[dict],
    content_catalog: dict | None,
) -> None:
    """주차별 focus_content 배정 — '이번 주에 무엇을 공부하는가'의 구체적 답.

    - 교습 단계(intro/post_lecture/objective_entry): 과목별 튜토리얼을 해당
      단계 주차들에 결정론적으로 균등 분할 배정
    - objective_entry: 합성 연습 세트 참조 추가
    - past_exam_rotation: 기출 연도를 오래된 순으로 순환 배정 (연도별 회독)
    - mock_exam: 최신 연도 실전 모의 응시
    - final: 오답 전면 복습
    항목의 refs는 /tutorials·/practice API 쿼리로 바로 해석 가능한 형태다.
    """
    for week in weeks:
        week["focus_content"] = []
    if not content_catalog:
        return

    subjects = [s["subject"] for s in subject_states]
    tutorials_by_subject = _catalog_tutorials_by_subject(content_catalog)
    real_years_by_subject: dict[str, dict[int, int]] = content_catalog.get("real_exam_years", {})
    synthetic_counts: dict[str, int] = content_catalog.get("synthetic_counts", {})
    all_years = sorted({y for years in real_years_by_subject.values() for y in years})

    teaching_idx = [i for i, w in enumerate(weeks) if w["stage"] in TEACHING_STAGES]
    for subject in subjects:
        tuts = tutorials_by_subject.get(subject, [])
        if not tuts or not teaching_idx:
            continue
        # 튜토리얼을 교습 주차에 균등 분할(앞 주차부터). n주에 m개 → 주당 ceil 분배.
        per_week = math.ceil(len(tuts) / len(teaching_idx))
        for slot, start in enumerate(range(0, len(tuts), per_week)):
            if slot >= len(teaching_idx):
                break
            for t in tuts[start : start + per_week]:
                weeks[teaching_idx[slot]]["focus_content"].append(
                    {
                        "type": "tutorial",
                        "subject": subject,
                        "tutorial_id": t["tutorial_id"],
                        "level": t.get("level"),
                        "ontology_node": t.get("ontology_node"),
                    }
                )

    rotation_slot = 0
    for week in weeks:
        stage = week["stage"]
        if stage == "objective_entry":
            for subject in subjects:
                count = synthetic_counts.get(subject, 0)
                if count:
                    week["focus_content"].append(
                        {
                            "type": "practice_set",
                            "subject": subject,
                            "source": "synthetic",
                            "available_questions": count,
                            "api_query": f"/practice?source=synthetic&subject={subject}",
                        }
                    )
        elif stage == "past_exam_rotation" and all_years:
            year = all_years[rotation_slot % len(all_years)]
            rotation_slot += 1
            for subject in subjects:
                count = real_years_by_subject.get(subject, {}).get(year, 0)
                if count:
                    week["focus_content"].append(
                        {
                            "type": "real_exam_set",
                            "subject": subject,
                            "year": year,
                            "available_questions": count,
                            "api_query": f"/practice?source=real_exam&year={year}&subject={subject}",
                        }
                    )
        elif stage == "mock_exam" and all_years:
            year = all_years[-1]
            week["focus_content"].append(
                {
                    "type": "mock_exam",
                    "year": year,
                    "note": f"{year}년 기출 전 과목을 실제 시험 시간 배분으로 응시한다.",
                    "api_query": f"/practice?source=real_exam&year={year}",
                }
            )
        elif stage == "final":
            week["focus_content"].append(
                {
                    "type": "wrong_answer_review",
                    "note": "누적 오답 전면 재풀이 — /attempts에서 오답 문항을 조회해 재시도한다.",
                    "api_query": "/attempts",
                }
            )


def _fallback_plan(user_state: dict, hours_per_week: float) -> dict:
    """subject_states가 비었을 때의 진단 보강 1주 플랜."""
    n = len(FALLBACK_SUBJECTS)
    per_subject = round(hours_per_week / n, 2) if hours_per_week > 0 else 0.0
    hours_list = [per_subject] * n
    drift = round(hours_per_week - per_subject * n, 2)
    if abs(drift) >= 0.01:
        hours_list[0] = round(hours_list[0] + drift, 2)

    allocation = [
        {
            "subject": subject,
            "hours": hours_list[i],
            "reason": (
                f"{name_ko(subject)} — 과목별 진단 데이터가 없어 "
                f"풀이 로그 수집을 위해 균등 배정한다."
            ),
        }
        for i, subject in enumerate(FALLBACK_SUBJECTS)
    ]
    week = {
        "week_no": 1,
        "days_range": _days_range(int(user_state["days_until_exam"]), 1),
        "stage": user_state["current_stage"],
        "theme": "진단 보강 주간 — 풀이 로그 수집",
        "subject_allocation": allocation,
        "milestone": "전 과목 풀이 로그 50건 이상 누적, 모든 풀이에 오답 원인 분류 입력",
        "verification_metric": "풀이 로그 50건 이상 누적되어 과목별 정답률 산출이 가능해진다",
    }
    return {
        "total_weeks": 1,
        "hours_per_week": hours_per_week,
        "pass_bar": {"average": PASS_AVERAGE, "per_subject_floor": PASS_SUBJECT_FLOOR},
        "weeks": [week],
        "strategy_summary": (
            "과목별 진단 데이터가 없어 정식 로드맵 대신 진단 보강 1주 플랜을 제공한다. "
            "풀이 로그가 쌓이면 정식 다주차 플랜을 재생성한다."
        ),
        "evidence_refs": _evidence_refs(user_state),
    }


def build_study_plan(
    user_state: dict,
    *,
    max_weeks: int = DEFAULT_MAX_WEEKS,
    content_catalog: dict | None = None,
) -> dict:
    """D-day 기반 다주차 학습 로드맵을 생성한다.

    동일 user_state 입력은 동일 출력을 보장한다. 모든 주에 측정 가능한
    verification_metric을, 모든 과목 배분에 한국어 reason을 첨부하고,
    evidence_refs로 근거 추적이 가능하다.

    content_catalog가 주어지면 주차별 focus_content(튜토리얼/문항 세트 배정)를
    채운다 — 주차 테마 문자열만으로는 '이번 주에 무엇을 공부할지'를 알 수 없다.
    """
    days = int(user_state["days_until_exam"])
    hours_per_week = round(float(user_state["available_hours_per_day"]) * 7, 2)
    # 같은 과목이 중복 입력되면 과락 floor가 중복 적용되어 배분이 깨진다 —
    # 첫 등장만 유지(결정론 dedupe). API 경계에서도 422로 거부하지만 엔진도 방어.
    subject_states: list[dict] = []
    seen_subjects: set[str] = set()
    for state in user_state.get("subject_states", []):
        if state["subject"] not in seen_subjects:
            seen_subjects.add(state["subject"])
            subject_states.append(state)

    if not subject_states:
        return _fallback_plan(user_state, hours_per_week)

    total_weeks = _total_weeks(days, max_weeks)
    stages = _remaining_stages(user_state["current_stage"])
    stage_weeks = _distribute_stage_weeks(stages, total_weeks)
    allocation = _allocate_subject_hours(subject_states, hours_per_week)

    weeks: list[dict] = []
    week_no = 0
    for stage, count in stage_weeks:
        for i in range(1, count + 1):
            week_no += 1
            weeks.append(
                {
                    "week_no": week_no,
                    "days_range": _days_range(days, week_no),
                    "stage": stage,
                    "theme": STAGE_THEMES[stage],
                    "subject_allocation": [dict(item) for item in allocation],
                    "milestone": f"{STAGE_MILESTONES[stage]} ({i}/{count}주차)",
                    "verification_metric": STAGE_METRICS[stage],
                }
            )

    # 마지막 주는 항상 모의/최종 점검 + 과락 방어 체크.
    weeks[-1]["milestone"] = FINAL_WEEK_MILESTONE
    weeks[-1]["verification_metric"] = FINAL_WEEK_METRIC

    _assign_week_content(weeks, subject_states, content_catalog)

    return {
        "total_weeks": total_weeks,
        "hours_per_week": hours_per_week,
        "pass_bar": {"average": PASS_AVERAGE, "per_subject_floor": PASS_SUBJECT_FLOOR},
        "weeks": weeks,
        "feasibility": _feasibility(user_state["current_stage"], total_weeks, hours_per_week),
        "strategy_summary": _strategy_summary(user_state, total_weeks, stage_weeks),
        "evidence_refs": _evidence_refs(user_state),
    }
