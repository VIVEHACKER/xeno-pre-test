"""결정론적 문제 추천 엔진.

처방(prescribe)의 빈 problems_to_solve / problems_to_skip을 채운다.
동일 입력 → 동일 출력(시각/난수 미사용). 모든 추천 항목에 한국어 reason과
problem_solution_map evidence_refs를 첨부해 근거 추적이 가능하다.

우선순위 점수 설계 (가중치는 모듈 상수로 노출):
1) 과목 약점 — accuracy가 낮을수록 가중. 과락선(0.40) 미만 과목은
   WEIGHT_FAIL_RISK_BONUS를 더해 비과락 과목보다 항상 앞서도록 보장.
2) 개념 약점 — concept_mastery < 0.5 개념이 문항 concept_tags와 부분 문자열
   매칭되면 강한 가중. 매칭 여부로 1회만 가산한다 — 매칭 개수만큼 누적하면
   과락 과목 최우선 불변량(아래 주석)이 깨질 수 있기 때문.
3) 미응시 우선 — attempted_question_ids에 포함된 문항은 감점.
   (틀린 문항 재출제 로직은 attempted에 정오 정보가 없어 단순 감점만 적용)
4) time_pressure 보정 — 과목 risk_tags에 time_pressure가 있고 문항에
   expected_seconds가 있으면 SHORT_PROBLEM_SECONDS 이하 단문항에 소폭 가중.
   expected_seconds가 없는 문항(대부분)은 무시.
동점 시 question_id 오름차순(결정론).

콜드스타트 처리:
- subject_states에 없는 과목 문항은 NEUTRAL_ACCURACY 가정의 중립 점수 (차단 금지).
- subject_states 자체가 비어 있으면 과목 균등(라운드로빈) 추천으로 폴백.

problems_to_skip: 안정권 과목(accuracy >= STABLE_ACCURACY) 문항 중 추천되지 않은
것 상위 n_skip — 약점 과목에 시간을 배분하라는 한국어 근거를 붙인다.
"""

from __future__ import annotations

from cpa_first.subjects import SUBJECTS

# 합격 기준 임계값. CPA 1차: 전 과목 평균 60% 이상 AND 매 과목 40% 이상(과락).
FAIL_RISK_ACCURACY = 0.40
AVERAGE_PASS_ACCURACY = 0.60
STABLE_ACCURACY = 0.75
WEAK_CONCEPT_MASTERY = 0.50
NEUTRAL_ACCURACY = 0.50  # subject_states에 없는 과목의 중립 가정치
SHORT_PROBLEM_SECONDS = 90  # time_pressure 사용자에게 선호되는 단문항 기준

# 우선순위 점수 가중치.
# 불변량(과락 최우선): 과락 과목 최소 점수 > 비과락 과목 최대 점수 (동일 응시 이력 기준)
#   과락 최소 = 0.6 * WEIGHT_SUBJECT_WEAKNESS + WEIGHT_FAIL_RISK_BONUS = 2.1
#   비과락 최대 = 0.6 * WEIGHT_SUBJECT_WEAKNESS + WEIGHT_WEAK_CONCEPT_MATCH
#              + WEIGHT_TIME_FIT = 1.6
# 가중치 변경 시 위 부등식을 유지할 것.
WEIGHT_SUBJECT_WEAKNESS = 1.0
WEIGHT_FAIL_RISK_BONUS = 1.5
WEIGHT_WEAK_CONCEPT_MATCH = 0.8
WEIGHT_TIME_FIT = 0.2
PENALTY_ATTEMPTED = 0.5


def _subject_label(subject: str) -> str:
    meta = SUBJECTS.get(subject)
    return meta.name_ko if meta else subject


def _unique_items(solution_maps: list[dict]) -> list[dict]:
    """question_id 중복 제거 (첫 등장 유지). 입력 순서 무관 결정론을 위해 정렬은 호출부에서."""
    seen: set[str] = set()
    items: list[dict] = []
    for item in solution_maps:
        qid = str(item["question_id"])
        if qid in seen:
            continue
        seen.add(qid)
        items.append(item)
    return items


def _weak_concepts(state: dict | None) -> list[tuple[str, float]]:
    """concept_mastery < WEAK_CONCEPT_MASTERY 개념 목록. concept 오름차순 결정론."""
    if not state:
        return []
    weak = [
        (str(cm["concept"]), float(cm["mastery"]))
        for cm in state.get("concept_mastery") or []
        if float(cm["mastery"]) < WEAK_CONCEPT_MASTERY
    ]
    weak.sort(key=lambda pair: (pair[0], pair[1]))
    return weak


def _matched_weak_concepts(weak: list[tuple[str, float]], concept_tags: list[str]) -> list[str]:
    """약점 개념과 문항 concept_tags의 부분 문자열 매칭. 매칭된 개념명 오름차순."""
    matched: list[str] = []
    for concept, _mastery in weak:
        for tag in concept_tags:
            tag_str = str(tag)
            if concept in tag_str or tag_str in concept:
                matched.append(concept)
                break
    return matched


def _score_item(
    item: dict,
    state: dict | None,
    attempted_question_ids: set[str] | frozenset,
) -> tuple[float, str, list[str]]:
    """문항 1개의 (priority_score, 한국어 reason, 매칭 약점 개념) 산출. 순수 함수."""
    subject = str(item["subject"])
    label = _subject_label(subject)
    reasons: list[str] = []
    score = 0.0

    # ① 과목 약점 가중 (+과락 보너스)
    if state is None:
        accuracy = NEUTRAL_ACCURACY
        reasons.append(f"{label}은(는) 풀이 이력이 없어 중립 점수로 탐색 추천")
    else:
        accuracy = float(state["accuracy"])
        if accuracy < FAIL_RISK_ACCURACY:
            reasons.append(f"{label} 정답률 {accuracy:.0%} — 과락선(40%) 미만 최우선 보강 대상")
        elif accuracy < AVERAGE_PASS_ACCURACY:
            reasons.append(f"{label} 정답률 {accuracy:.0%} — 평균 합격선(60%) 미달 보강 대상")
        else:
            reasons.append(f"{label} 정답률 {accuracy:.0%} 기준 우선순위 산정")
    score += WEIGHT_SUBJECT_WEAKNESS * (1.0 - max(0.0, min(1.0, accuracy)))
    if state is not None and accuracy < FAIL_RISK_ACCURACY:
        score += WEIGHT_FAIL_RISK_BONUS

    # ② 개념 약점 매칭 가중 (매칭 여부 1회 가산)
    matched = _matched_weak_concepts(_weak_concepts(state), item.get("concept_tags") or [])
    if matched:
        score += WEIGHT_WEAK_CONCEPT_MATCH
        joined = ", ".join(matched)
        reasons.append(f"약점 개념({joined}, 숙련도 {WEAK_CONCEPT_MASTERY:.0%} 미만) 보강 문항")

    # ③ 미응시 우선 — 응시 이력 감점
    qid = str(item["question_id"])
    if qid in attempted_question_ids:
        score -= PENALTY_ATTEMPTED
        reasons.append("이미 응시한 문항이라 미응시 문항 대비 후순위")

    # ④ time_pressure 보정 — expected_seconds가 있을 때만
    risk_tags = set(state.get("risk_tags") or []) if state else set()
    expected_seconds = item.get("expected_seconds")
    if (
        "time_pressure" in risk_tags
        and isinstance(expected_seconds, (int, float))
        and expected_seconds <= SHORT_PROBLEM_SECONDS
    ):
        score += WEIGHT_TIME_FIT
        reasons.append(
            f"시간 압박(time_pressure) 대응 — 예상 풀이 {int(expected_seconds)}초 단문항 선호"
        )

    return round(score, 4), ". ".join(reasons) + ".", matched


def _solve_entry(item: dict, score: float, reason: str, matched: list[str]) -> dict:
    note = f"unit={item['unit']}"
    if matched:
        note += "; 약점 개념 매칭: " + ", ".join(matched)
    else:
        note += "; 과목 정답률 신호 기반"
    return {
        "question_id": item["question_id"],
        "subject": item["subject"],
        "unit": item["unit"],
        "reason": reason,
        "priority_score": score,
        "evidence_refs": [
            {
                "ref_type": "problem_solution_map",
                "ref_id": item["question_id"],
                "note": note,
            }
        ],
    }


def _balanced_solve_entries(items: list[dict], n_solve: int) -> list[dict]:
    """콜드스타트 폴백: 과목 오름차순 라운드로빈으로 균등 추천."""
    by_subject: dict[str, list[dict]] = {}
    for item in sorted(items, key=lambda m: str(m["question_id"])):
        by_subject.setdefault(str(item["subject"]), []).append(item)

    neutral_score = round(WEIGHT_SUBJECT_WEAKNESS * (1.0 - NEUTRAL_ACCURACY), 4)
    entries: list[dict] = []
    subjects = sorted(by_subject)
    while len(entries) < n_solve and any(by_subject[s] for s in subjects):
        for subject in subjects:
            if len(entries) >= n_solve:
                break
            if not by_subject[subject]:
                continue
            item = by_subject[subject].pop(0)
            reason = (
                f"학습 이력이 없어 과목 균등 탐색 추천 — "
                f"{_subject_label(subject)} 진단 데이터 확보 목적."
            )
            entry = _solve_entry(item, neutral_score, reason, [])
            entry["evidence_refs"][0]["note"] = f"unit={item['unit']}; 콜드스타트 균등 추천"
            entries.append(entry)
    return entries


def _skip_entries(
    items: list[dict],
    states_by_subject: dict[str, dict],
    solved_question_ids: set[str],
    n_skip: int,
) -> list[dict]:
    stable_accuracy = {
        subject: float(state["accuracy"])
        for subject, state in states_by_subject.items()
        if float(state["accuracy"]) >= STABLE_ACCURACY
    }
    candidates = [
        item
        for item in items
        if str(item["subject"]) in stable_accuracy
        and str(item["question_id"]) not in solved_question_ids
    ]
    # 더 안정적인 과목부터, 동률 시 question_id 오름차순 (결정론)
    candidates.sort(key=lambda m: (-stable_accuracy[str(m["subject"])], str(m["question_id"])))

    entries: list[dict] = []
    for item in candidates[:n_skip]:
        subject = str(item["subject"])
        accuracy = stable_accuracy[subject]
        entries.append(
            {
                "question_id": item["question_id"],
                "subject": item["subject"],
                "unit": item["unit"],
                "reason": (
                    f"{_subject_label(subject)}은(는) 이미 안정권(정답률 {accuracy:.0%}) — "
                    f"약점 과목에 시간 배분 권장."
                ),
            }
        )
    return entries


def recommend_problems(
    user_state: dict,
    solution_maps: list[dict],
    *,
    attempted_question_ids: set[str] | frozenset = frozenset(),
    n_solve: int = 5,
    n_skip: int = 3,
) -> dict:
    """user_state 약점 신호로 problems_to_solve / problems_to_skip을 산출한다.

    반환 스키마:
    - problems_to_solve: [{question_id, subject, unit, reason, priority_score,
      evidence_refs: [{ref_type: "problem_solution_map", ref_id, note}]}]
    - problems_to_skip: [{question_id, subject, unit, reason}]
    """
    n_solve = max(0, int(n_solve))
    n_skip = max(0, int(n_skip))
    items = _unique_items(solution_maps)
    states_by_subject = {
        str(state["subject"]): state for state in user_state.get("subject_states") or []
    }

    # 폴백: 모든 과목이 빈 상태 → 과목 균등 추천 (skip 판단 근거 없음)
    if not states_by_subject:
        return {
            "problems_to_solve": _balanced_solve_entries(items, n_solve),
            "problems_to_skip": [],
        }

    scored: list[tuple[float, str, dict, str, list[str]]] = []
    for item in items:
        state = states_by_subject.get(str(item["subject"]))
        score, reason, matched = _score_item(item, state, attempted_question_ids)
        scored.append((score, str(item["question_id"]), item, reason, matched))
    # 점수 내림차순, 동점 시 question_id 오름차순 (결정론)
    scored.sort(key=lambda row: (-row[0], row[1]))

    solve_entries = [
        _solve_entry(item, score, reason, matched)
        for score, _qid, item, reason, matched in scored[:n_solve]
    ]
    solved_question_ids = {str(entry["question_id"]) for entry in solve_entries}

    return {
        "problems_to_solve": solve_entries,
        "problems_to_skip": _skip_entries(items, states_by_subject, solved_question_ids, n_skip),
    }
