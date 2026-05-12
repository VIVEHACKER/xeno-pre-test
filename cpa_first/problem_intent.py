from __future__ import annotations

from typing import Any


QUESTION_TYPE_TOKENS = (
    ("옳지 않은", "statement_selection"),
    ("아닌", "statement_selection"),
    ("옳은", "statement_selection"),
    ("얼마", "calculation"),
    ("금액", "calculation"),
    ("계산", "calculation"),
    ("해당", "classification"),
    ("분류", "classification"),
)

COMMON_TARGETS = (
    "이자수익",
    "손상차손",
    "기말재고",
    "매출원가",
    "수익",
    "손익분기점",
    "안전한계율",
    "종합과세 대상",
    "면세 대상",
    "정답",
)


def infer_question_type(stem: str) -> str:
    for token, question_type in QUESTION_TYPE_TOKENS:
        if token in stem:
            return question_type
    return "mixed"


def infer_target_entity(stem: str, profile: dict[str, Any]) -> str:
    for target in COMMON_TARGETS:
        if target in stem:
            return target
    for signal in profile.get("signals", []):
        if signal and signal in stem:
            return signal
    return profile.get("core", "정답 판단")


def infer_ask_verb(question_type: str) -> str:
    if question_type == "calculation":
        return "calculate"
    if question_type == "classification":
        return "classify"
    if question_type == "statement_selection":
        return "select"
    return "solve"


def concept_phrase(core: str) -> str:
    if core.endswith("개념") or core.endswith("체계") or core.endswith("분류"):
        return core
    return f"{core} 개념"


def analyze_question_intent(question: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    stem = question["stem"]
    signals = [signal for signal in profile.get("signals", []) if signal]
    core = profile.get("core", "핵심 개념")
    core_phrase = concept_phrase(core)
    trap = profile.get("trap", "조건 누락 함정")
    question_type = infer_question_type(stem)
    target = infer_target_entity(stem, profile)

    stem_conditions = [
        {
            "text": signal,
            "role": "trigger",
            "why_it_matters": f"{signal} 신호가 {core_phrase} 적용 여부를 결정한다.",
        }
        for signal in signals[:2]
    ]
    stem_conditions.append(
        {
            "text": target,
            "role": "ask",
            "why_it_matters": "문제가 최종적으로 요구하는 산출물이다.",
        }
    )
    stem_conditions.append(
        {
            "text": trap,
            "role": "distractor",
            "why_it_matters": "출제자가 오답 선택지를 만들기 위해 넣은 대표 혼동 지점이다.",
        }
    )

    return {
        "examiner_intent": f"문항 조건에서 필요한 개념 체계({core_phrase})를 식별하고 요구 산출물({target})까지 연결하는 능력을 본다.",
        "question_type": question_type,
        "asked_output": target,
        "concept_combination": [
            {
                "concept": core,
                "paired_with": signals[:3],
                "why_combined": "단일 암기가 아니라 조건 신호, 계산 또는 분류 기준, 오답 함정을 동시에 판별하게 하려는 조합이다.",
                "examiner_objective": f"요구 산출물({target})을 구하기 전에 어떤 개념 체계를 먼저 선택해야 하는지 검증한다.",
            }
        ],
        "stem_conditions": stem_conditions,
        "question_stem_parse": {
            "ask_verb": infer_ask_verb(question_type),
            "target_entity": target,
            "time_scope": "stem-defined",
            "negation": "아닌" in stem or "옳지 않은" in stem,
            "unit_or_rounding": "stem-defined",
            "must_not_miss": signals[:3],
        },
        "intent_hypothesis": {
            "primary": f"정답 계산 전에 {core_phrase} 체계를 선택할 수 있는지 검증한다.",
            "secondary": [
                f"{trap}을 피하는지 확인한다.",
                "본문 조건과 보기의 오답 유인을 연결해 판별하게 한다.",
            ],
            "confidence": 0.78,
        },
    }
