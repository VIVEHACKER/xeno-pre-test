"""5문항 배치 생성.

invoke(system, user) → 모델 raw 출력 문자열.
실패 시 max_retries 만큼 재시도.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from cpa_first.eval_gen._json_extract import extract_json_object


SYSTEM_PROMPT = """당신은 한국 공인회계사 1차 시험(회계학·세법개론) 출제위원입니다.
다음 규칙을 엄격히 지킵니다.

1. 회계학은 K-IFRS, 세법은 적용연도(applicable_year)를 명시한다.
2. 4지선다 객관식. 정답은 유일해야 한다.
3. 매력적 오답(attractive distractors)을 반드시 포함한다 — 계산 실수 유도, 자주 헷갈리는 정의·조문, 부호·연도 혼동 등.
4. 출력은 JSON만. 코드블록(```json) 사용 가능. 다른 설명 금지.
5. 각 문항에 다음 키를 채운다: exam='CPA_1', subject, unit, applicable_year, stem, choices(4-5개), correct_choice(0-기반), explanation, concept_tags, expected_seconds, difficulty, difficulty_score, bloom_level.
6. difficulty와 difficulty_score 매핑: easy=1-2, mid=3, hard=4-5. bloom_level은 remember/understand/apply/analyze/evaluate 중 하나.

출력 스키마:
{
  "questions": [
    { ...evaluation_question 객체 1... },
    ...
  ]
}"""


USER_TEMPLATE = """[목표]
과목: {subject}
단원: {unit}
난이도: {difficulty}
요청 건수: {count}
적용연도: 2026

[지시]
- 단원 {unit}에 해당하는 {difficulty} 난이도 문항을 {count}개 생성한다.
- 한 단원 안에서 서로 다른 풀이 패턴이 나오도록 변형한다.
- 정답이 보기 0번에만 몰리지 않도록 분산한다.
- explanation에는 풀이 단계와 근거 조문/기준을 명시한다.
- concept_tags는 한국어 개념 키워드 3-5개.

[예시 (참고만, 그대로 베끼지 말 것)]
{example}

위 지시에 따라 JSON {{"questions": [...]}} 만 출력한다."""


@dataclass
class BatchSpec:
    subject: str
    unit: str
    difficulty: str  # easy / mid / hard
    count: int
    example: str = ""  # 단원별 예시 문항 (선택)


def _build_user_prompt(spec: BatchSpec) -> str:
    return USER_TEMPLATE.format(
        subject=spec.subject,
        unit=spec.unit,
        difficulty=spec.difficulty,
        count=spec.count,
        example=spec.example or "(예시 없음)",
    )


def _hydrate(q: dict[str, Any], spec: BatchSpec) -> dict[str, Any]:
    """모델 출력의 누락 필드를 spec/기본값으로 채운다."""
    q.setdefault("exam", "CPA_1")
    q.setdefault("subject", spec.subject)
    q.setdefault("unit", spec.unit)
    q.setdefault("difficulty", spec.difficulty)
    q.setdefault("applicable_year", 2026)
    q.setdefault("expected_seconds", _expected_seconds(spec.difficulty))
    q.setdefault("difficulty_score", _score_for(spec.difficulty))
    q.setdefault("bloom_level", _bloom_for(spec.difficulty))
    q.setdefault("concept_tags", [])
    q["rights_status"] = "synthetic_seed"
    q["review_status"] = "ai_draft"
    return q


def _expected_seconds(difficulty: str) -> int:
    return {"easy": 60, "mid": 90, "hard": 120}.get(difficulty, 90)


def _score_for(difficulty: str) -> int:
    return {"easy": 2, "mid": 3, "hard": 4}.get(difficulty, 3)


def _bloom_for(difficulty: str) -> str:
    return {"easy": "understand", "mid": "apply", "hard": "analyze"}.get(difficulty, "apply")


def generate_batch(
    spec: BatchSpec,
    invoke: Callable[[str, str], str],
    *,
    max_retries: int = 1,
) -> list[dict[str, Any]]:
    """모델 출력을 파싱하여 evaluation_question dict 리스트를 반환.

    파싱 실패 시 max_retries 만큼 재시도. 그래도 실패하면 빈 리스트.
    """
    user = _build_user_prompt(spec)
    last_raw = ""
    for attempt in range(max_retries + 1):
        last_raw = invoke(SYSTEM_PROMPT, user) or ""
        parsed = extract_json_object(last_raw)
        if isinstance(parsed, dict) and isinstance(parsed.get("questions"), list):
            questions = [
                _hydrate(dict(q), spec)
                for q in parsed["questions"]
                if isinstance(q, dict) and q.get("choices") and "correct_choice" in q
            ]
            if questions:
                return questions
    return []
