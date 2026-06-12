"""문제 추천 엔진 단위 테스트.

검증 목표:
1) 과락 과목 최우선 추천
2) 약점 개념 부분 문자열 매칭 가중
3) 응시 이력 감점 (미응시 우선)
4) 안정권 과목 skip + 한국어 근거
5) 결정론: 동일 입력 → 동일 출력 (입력 순서 무관)
6) 빈 subject_states → 과목 균등 폴백
7) 실데이터 스모크: prototype/problem_solution_maps.json 5건 추천 스키마 검증
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cpa_first.engine.recommend import recommend_problems

ROOT = Path(__file__).resolve().parents[1]
SOLUTION_MAPS_PATH = ROOT / "prototype" / "problem_solution_maps.json"

SOLVE_KEYS = {"question_id", "subject", "unit", "reason", "priority_score", "evidence_refs"}
SKIP_KEYS = {"question_id", "subject", "unit", "reason"}


def _user_state(subject_states: list[dict]) -> dict:
    return {
        "user_id": "u-recommend-test",
        "target_exam": "CPA_1",
        "days_until_exam": 90,
        "available_hours_per_day": 6.0,
        "current_stage": "objective_entry",
        "subject_states": subject_states,
    }


def _subject_state(subject: str, accuracy: float, **extra) -> dict:
    state = {
        "subject": subject,
        "accuracy": accuracy,
        "time_overrun_rate": 0.1,
        "risk_tags": [],
    }
    state.update(extra)
    return state


def _item(qid: str, subject: str, unit: str = "basics", tags: list[str] | None = None, **extra):
    item = {
        "question_id": qid,
        "subject": subject,
        "unit": unit,
        "stem": f"{qid} 문제 지문",
        "choices": ["보기1", "보기2", "보기3", "보기4"],
        "correct_choice": 1,
        "explanation": "해설",
        "concept_tags": tags or [],
        "solution_paths": [],
        "tutorial_id": f"tutorial_cpa1_{subject}",
    }
    item.update(extra)
    return item


def test_fail_risk_subject_recommended_first():
    """과락선(40%) 미만 과목 문항이 약개념 매칭 과목보다도 앞선다."""
    user = _user_state(
        [
            _subject_state("tax", 0.35),
            _subject_state(
                "accounting",
                0.55,
                concept_mastery=[{"concept": "재무회계: 금융자산", "mastery": 0.2}],
            ),
        ]
    )
    maps = [
        _item("q-acc-1", "accounting", tags=["재무회계: 금융자산"]),
        _item("q-acc-2", "accounting", tags=["재무회계: 금융자산"]),
        _item("q-tax-1", "tax", unit="vat"),
        _item("q-tax-2", "tax", unit="vat"),
        _item("q-tax-3", "tax", unit="income_tax"),
    ]

    result = recommend_problems(user, maps, n_solve=3, n_skip=0)
    solve = result["problems_to_solve"]

    assert [entry["subject"] for entry in solve] == ["tax", "tax", "tax"]
    assert [entry["question_id"] for entry in solve] == ["q-tax-1", "q-tax-2", "q-tax-3"]
    assert "과락선" in solve[0]["reason"]
    assert "35%" in solve[0]["reason"]


def test_weak_concept_partial_match_boosts():
    """concept_mastery<0.5 개념이 concept_tags와 부분 문자열 매칭되면 가중된다."""
    user = _user_state(
        [
            _subject_state(
                "accounting",
                0.55,
                concept_mastery=[
                    {"concept": "금융자산", "mastery": 0.3},  # 부분 문자열 매칭 검증
                    {"concept": "재무회계: 수익인식", "mastery": 0.9},  # 약점 아님
                ],
            ),
        ]
    )
    maps = [
        _item("q-acc-1", "accounting", tags=["재무회계: 수익인식"]),  # qid 순서상 앞
        _item("q-acc-2", "accounting", tags=["재무회계: 금융자산"]),
    ]

    result = recommend_problems(user, maps, n_solve=2, n_skip=0)
    solve = result["problems_to_solve"]

    # 가중이 없다면 동점 → q-acc-1이 먼저. 약개념 매칭 가중으로 q-acc-2가 역전.
    assert [entry["question_id"] for entry in solve] == ["q-acc-2", "q-acc-1"]
    assert solve[0]["priority_score"] > solve[1]["priority_score"]
    assert "약점 개념" in solve[0]["reason"]
    assert "금융자산" in solve[0]["evidence_refs"][0]["note"]


def test_attempted_question_penalized():
    """attempted_question_ids에 포함된 문항은 감점되어 미응시 문항이 앞선다."""
    user = _user_state([_subject_state("tax", 0.5)])
    maps = [_item("q-tax-1", "tax"), _item("q-tax-2", "tax")]

    result = recommend_problems(
        user, maps, attempted_question_ids=frozenset({"q-tax-1"}), n_solve=2, n_skip=0
    )
    solve = result["problems_to_solve"]

    assert [entry["question_id"] for entry in solve] == ["q-tax-2", "q-tax-1"]
    assert solve[0]["priority_score"] > solve[1]["priority_score"]
    assert "응시" in solve[1]["reason"]


def test_stable_subject_skipped_with_korean_reason():
    """안정권(>=75%) 과목 문항은 추천에서 빠지고 skip에 한국어 근거가 붙는다."""
    user = _user_state(
        [
            _subject_state("tax", 0.35),
            _subject_state("economics", 0.8),
        ]
    )
    maps = [_item(f"q-tax-{i}", "tax") for i in range(1, 6)] + [
        _item("q-eco-1", "economics"),
        _item("q-eco-2", "economics"),
        _item("q-eco-3", "economics"),
    ]

    result = recommend_problems(user, maps, n_solve=5, n_skip=2)

    assert all(entry["subject"] == "tax" for entry in result["problems_to_solve"])
    skip = result["problems_to_skip"]
    assert [entry["question_id"] for entry in skip] == ["q-eco-1", "q-eco-2"]
    for entry in skip:
        assert set(entry.keys()) == SKIP_KEYS
        assert "안정권" in entry["reason"]
        assert "80%" in entry["reason"]
        assert "시간 배분" in entry["reason"]

    solve_ids = {entry["question_id"] for entry in result["problems_to_solve"]}
    assert solve_ids.isdisjoint({entry["question_id"] for entry in skip})


def test_deterministic_same_input_same_output():
    """같은 입력 2회 + 입력 순서 뒤집기 → 동일 출력."""
    user = _user_state(
        [
            _subject_state("tax", 0.35),
            _subject_state(
                "accounting",
                0.55,
                concept_mastery=[{"concept": "재무회계: 금융자산", "mastery": 0.2}],
            ),
            _subject_state("economics", 0.85),
        ]
    )
    maps = [
        _item("q-acc-1", "accounting", tags=["재무회계: 금융자산"]),
        _item("q-acc-2", "accounting"),
        _item("q-tax-1", "tax"),
        _item("q-tax-2", "tax"),
        _item("q-eco-1", "economics"),
        _item("q-eco-2", "economics"),
    ]

    first = recommend_problems(user, maps, attempted_question_ids=frozenset({"q-tax-1"}))
    second = recommend_problems(user, maps, attempted_question_ids=frozenset({"q-tax-1"}))
    reversed_input = recommend_problems(
        user, list(reversed(maps)), attempted_question_ids=frozenset({"q-tax-1"})
    )

    dump = lambda rx: json.dumps(rx, sort_keys=True, ensure_ascii=False)  # noqa: E731
    assert dump(first) == dump(second)
    assert dump(first) == dump(reversed_input)


def test_empty_subject_states_balanced_fallback():
    """subject_states가 비면 과목 균등(라운드로빈) 추천, skip은 빈 리스트."""
    user = _user_state([])
    maps = [
        _item("q-acc-1", "accounting"),
        _item("q-acc-2", "accounting"),
        _item("q-acc-3", "accounting"),
        _item("q-acc-4", "accounting"),
        _item("q-eco-1", "economics"),
        _item("q-tax-1", "tax"),
    ]

    result = recommend_problems(user, maps, n_solve=3, n_skip=3)
    solve = result["problems_to_solve"]

    # 과목 오름차순 라운드로빈: accounting → economics → tax 각 1문항
    assert [entry["subject"] for entry in solve] == ["accounting", "economics", "tax"]
    assert all("균등" in entry["reason"] for entry in solve)
    assert result["problems_to_skip"] == []


def test_unknown_subject_gets_neutral_score():
    """subject_states에 없는 과목 문항도 중립 점수로 추천 가능 (콜드스타트 차단 금지)."""
    user = _user_state([_subject_state("accounting", 0.9)])
    maps = [_item("q-acc-1", "accounting"), _item("q-biz-1", "business")]

    result = recommend_problems(user, maps, n_solve=1, n_skip=0)
    top = result["problems_to_solve"][0]

    # 중립(0.5 가정) > 안정 과목(0.9) 약점 점수
    assert top["question_id"] == "q-biz-1"
    assert "이력이 없어" in top["reason"]


@pytest.mark.skipif(not SOLUTION_MAPS_PATH.exists(), reason="실데이터 시드 없음")
def test_real_solution_maps_smoke():
    """실데이터 스모크: 5개 추천이 스키마를 만족하고 근거 추적이 가능하다."""
    with SOLUTION_MAPS_PATH.open("r", encoding="utf-8") as f:
        maps = json.load(f)["problem_solution_maps"]

    user = _user_state(
        [
            _subject_state("tax", 0.35),
            _subject_state(
                "accounting",
                0.55,
                concept_mastery=[{"concept": "재무회계: 금융자산", "mastery": 0.3}],
            ),
            _subject_state("economics", 0.82),
        ]
    )

    result = recommend_problems(user, maps, n_solve=5, n_skip=3)
    solve = result["problems_to_solve"]
    skip = result["problems_to_skip"]

    assert len(solve) == 5
    assert len({entry["question_id"] for entry in solve}) == 5
    scores = [entry["priority_score"] for entry in solve]
    assert scores == sorted(scores, reverse=True)

    for entry in solve:
        assert set(entry.keys()) == SOLVE_KEYS
        assert isinstance(entry["priority_score"], float)
        assert entry["reason"].strip()
        assert len(entry["evidence_refs"]) >= 1
        ref = entry["evidence_refs"][0]
        assert ref["ref_type"] == "problem_solution_map"
        assert ref["ref_id"] == entry["question_id"]
        assert ref["note"].strip()

    # 과락 위험 tax가 최상위, 안정권 economics는 skip으로
    assert solve[0]["subject"] == "tax"
    assert len(skip) == 3
    for entry in skip:
        assert set(entry.keys()) == SKIP_KEYS
        assert entry["subject"] == "economics"
        assert "안정권" in entry["reason"]
