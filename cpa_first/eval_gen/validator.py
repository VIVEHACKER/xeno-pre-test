"""문항별 검증 라운드.

생성된 문항을 별도 prompt로 자체 검증한다. 출력 verdict:
- approve: 그대로 채택, attractor_traps 채움
- revise: revised 본문 채택
- reject: 폐기

cross_check=True 옵션을 켜면 최종 본문을 답·해설 가린 채 모델이 풀어보고
correct_choice와 대조한다. 불일치 시 cross_check_passed=False가 채워지므로
호출자(generate_eval_set.py)는 다음 패턴으로 flag를 자동 부여한다:

    result = validate_question(q, invoke, cross_check=True)
    if result.cross_check_passed is False:
        target = result.revised or q
        target["flagged_questionable"] = True
        target["questionable_reason"] = result.issues[-1]
    write_question(target, ...)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from cpa_first.eval_gen._json_extract import extract_json_object


SYSTEM_PROMPT = """당신은 한국 CPA 1차 시험 검토위원입니다.
주어진 객관식 문항을 채점위원 관점에서 점검합니다.

점검 항목:
1. 정답이 실제로 유일한 정답인가? (복수 정답·정답 없음 → reject)
2. 오답 보기가 매력적 오답 패턴을 따르는가? (명백한 오답뿐 → revise 또는 reject)
3. K-IFRS·세법 조문 인용이 정확한가? (오류 발견 → revise)
4. 난이도 태그(difficulty)가 실제 풀이 단계 수와 일치하는가?

출력은 JSON만 (코드블록 가능):
{
  "verdict": "approve" | "revise" | "reject",
  "issues": ["발견한 문제점 목록"],
  "attractor_traps": ["오답 보기가 노리는 함정 종류"],
  "revised": { ...수정된 evaluation_question 본문 (verdict=revise일 때만)... }
}"""


USER_TEMPLATE = """[검증할 문항]
{question_json}

위 문항을 점검하고 JSON으로 verdict/issues/attractor_traps/revised를 반환한다."""


@dataclass
class ValidationResult:
    verdict: str  # approve | revise | reject
    issues: list[str] = field(default_factory=list)
    attractor_traps: list[str] = field(default_factory=list)
    revised: dict[str, Any] | None = None
    raw: str = ""
    # 정답키 교차검증 결과 (cross_check 단계가 돌았을 때만)
    cross_check_chosen: int | None = None
    cross_check_passed: bool | None = None
    cross_check_rationale: str = ""


CROSS_CHECK_SYSTEM = """당신은 한국 CPA 1차 시험 응시자입니다. 답을 보지 않은 상태로 문항을 풀고
보기 인덱스(0-기반)를 골라야 합니다.

출력 규칙:
- 풀이 근거를 3~6줄로 압축한다.
- 마지막 줄을 "ANSWER: <index>" 형식으로 둔다.
- 회계기준·세법 조문이 명확하면 인용한다."""


CROSS_CHECK_USER_TEMPLATE = """과목: {subject}
단원: {unit}
{year_line}

[문제]
{stem}

[보기]
{choices_block}

위 절차에 따라 풀이하고 ANSWER 줄을 마지막에 둔다."""


def _build_cross_check_prompt(question: dict[str, Any]) -> str:
    choices_block = "\n".join(
        f"{i}. {c}" for i, c in enumerate(question["choices"])
    )
    year = question.get("applicable_year")
    year_line = f"적용연도: {year}" if year else "적용연도: 미지정"
    return CROSS_CHECK_USER_TEMPLATE.format(
        subject=question.get("subject", "?"),
        unit=question.get("unit", "?"),
        year_line=year_line,
        stem=question["stem"],
        choices_block=choices_block,
    )


def _extract_answer_index(raw: str, max_choices: int) -> int:
    import re
    m = re.search(r"ANSWER\s*:\s*(\d+)", raw or "", re.IGNORECASE)
    if not m:
        return -1
    i = int(m.group(1))
    return i if 0 <= i < max_choices else -1


def cross_check_question(
    question: dict[str, Any],
    invoke: Callable[[str, str], str],
) -> tuple[int, str]:
    """답·해설을 가린 채 별도 LLM 호출로 문항을 풀어 본다.

    출력: (chosen_index, raw_response). 파싱 실패면 -1.
    """
    user = _build_cross_check_prompt(question)
    raw = invoke(CROSS_CHECK_SYSTEM, user) or ""
    return _extract_answer_index(raw, len(question["choices"])), raw


def validate_question(
    question: dict[str, Any],
    invoke: Callable[[str, str], str],
    *,
    cross_check: bool = False,
    cross_check_invoke: Callable[[str, str], str] | None = None,
) -> ValidationResult:
    """1) 검토위원 prompt로 verdict 평가. 2) 선택적으로 답·해설 가린 cross_check.

    cross_check=True면 별도 호출로 모델이 문항을 풀어 본 결과를 correct_choice와 대조한다.
    불일치하면 verdict='approve'/'revise'였더라도 issues에 cross_check 실패를 추가하고
    cross_check_passed=False를 표시한다. 호출자는 이 값을 보고 flagged_questionable을 부여한다.
    """
    import json

    user = USER_TEMPLATE.format(
        question_json=json.dumps(question, ensure_ascii=False, indent=2)
    )
    raw = invoke(SYSTEM_PROMPT, user) or ""
    parsed = extract_json_object(raw)

    if not isinstance(parsed, dict) or "verdict" not in parsed:
        return ValidationResult(
            verdict="reject",
            issues=["JSON parse failed"],
            raw=raw,
        )

    verdict = parsed.get("verdict")
    if verdict not in {"approve", "revise", "reject"}:
        return ValidationResult(
            verdict="reject",
            issues=[f"unknown verdict: {verdict}"],
            raw=raw,
        )

    revised = parsed.get("revised") if verdict == "revise" else None
    if verdict == "revise" and not isinstance(revised, dict):
        return ValidationResult(
            verdict="reject",
            issues=["verdict=revise but no revised body"],
            raw=raw,
        )

    result = ValidationResult(
        verdict=verdict,
        issues=list(parsed.get("issues") or []),
        attractor_traps=list(parsed.get("attractor_traps") or []),
        revised=revised,
        raw=raw,
    )

    # 정답키 교차검증: 최종 채택될 본문을 풀어 본다(revised 있으면 revised, 아니면 원본).
    if cross_check and verdict != "reject":
        target = revised if revised else question
        invoker = cross_check_invoke or invoke
        chosen, cross_raw = cross_check_question(target, invoker)
        expected = target.get("correct_choice")
        result.cross_check_chosen = chosen
        result.cross_check_rationale = cross_raw
        if chosen < 0 or chosen != expected:
            result.cross_check_passed = False
            result.issues.append(
                f"cross_check_failed: model chose {chosen}, key={expected}"
            )
        else:
            result.cross_check_passed = True

    return result
