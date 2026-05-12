"""문항별 검증 라운드.

생성된 문항을 별도 prompt로 자체 검증한다. 출력 verdict:
- approve: 그대로 채택, attractor_traps 채움
- revise: revised 본문 채택
- reject: 폐기
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


def validate_question(
    question: dict[str, Any],
    invoke: Callable[[str, str], str],
) -> ValidationResult:
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
        # revise라고 했는데 revised 본문 없으면 reject로 강등
        return ValidationResult(
            verdict="reject",
            issues=["verdict=revise but no revised body"],
            raw=raw,
        )

    return ValidationResult(
        verdict=verdict,
        issues=list(parsed.get("issues") or []),
        attractor_traps=list(parsed.get("attractor_traps") or []),
        revised=revised,
        raw=raw,
    )
