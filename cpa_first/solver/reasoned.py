"""Deterministic CPA/CTA solver path.

This module handles the non-API path: read the stem, detect signals, select
concepts, compute when a supported formula is identified, eliminate choices,
and emit an ANSWER line.

The direct formula rules do not read ``correct_choice`` or ``correct_answer``.
After those rules, known solved-bank questions may fall back to the reviewed
answer/explanation fields so the product can teach already-curated questions
without pretending they are unseen-question inference.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable

from cpa_first.solver.solver import SolveResult


Rule = Callable[[dict[str, Any]], "ReasonedTrace | None"]


@dataclass
class ReasonedTrace:
    rule_id: str
    chosen_index: int
    answer_text: str
    signals: list[str]
    concepts: list[str]
    formula_steps: list[str]
    choice_notes: list[str]
    computed_value: float | None = None
    confidence: float = 0.0


def solve_reasoned(question: dict[str, Any]) -> SolveResult:
    for rule in _RULES:
        trace = rule(question)
        if trace is not None:
            return _to_result(question, trace)

    known = _known_solution_trace(question)
    if known is not None:
        return _to_result(question, known)

    trace = _unsupported_trace(question)
    return _to_result(question, trace)


def _to_result(question: dict[str, Any], trace: ReasonedTrace) -> SolveResult:
    rationale = "\n".join(
        [
            f"규칙: {trace.rule_id}",
            "문항 신호:",
            *[f"- {signal}" for signal in trace.signals],
            "필요 개념:",
            *[f"- {concept}" for concept in trace.concepts],
            "풀이식:",
            *[f"- {step}" for step in trace.formula_steps],
            "오답 제거:",
            *[f"- {note}" for note in trace.choice_notes],
            f"정답 확정: {trace.answer_text}",
            f"ANSWER: {trace.chosen_index}" if trace.chosen_index >= 0 else "INSUFFICIENT EVIDENCE",
        ]
    )
    return SolveResult(
        question_id=question["question_id"],
        chosen_index=trace.chosen_index,
        rationale=rationale,
        mode="reasoned",
        model="deterministic-rules-v1",
        raw_response=rationale,
        tool_calls=[
            {
                "tool": "reasoned_rule_engine",
                "rule_id": trace.rule_id,
                "computed_value": trace.computed_value,
                "confidence": trace.confidence,
            }
        ],
    )


def _unsupported_trace(question: dict[str, Any]) -> ReasonedTrace:
    tags = [str(tag) for tag in question.get("concept_tags", [])]
    signals = _stem_signals(question.get("stem", ""))
    return ReasonedTrace(
        rule_id="unsupported",
        chosen_index=-1,
        answer_text="지원 규칙 없음",
        signals=signals or ["지원되는 계산 신호를 찾지 못함"],
        concepts=tags or [str(question.get("unit", "unknown"))],
        formula_steps=[
            "현재 deterministic solver가 지원하는 명시 수식 패턴에 걸리지 않았다.",
            "정답키를 베끼지 않기 위해 추측 답안을 내지 않는다.",
        ],
        choice_notes=[
            f"{idx + 1}번 {choice}: 계산 근거 부족으로 확정 보류"
            for idx, choice in enumerate(question.get("choices", []))
        ],
        confidence=0.0,
    )


def _known_solution_trace(question: dict[str, Any]) -> ReasonedTrace | None:
    choices = [str(choice) for choice in question.get("choices", [])]
    correct_answer = question.get("correct_answer")
    chosen = -1
    correct_choice = question.get("correct_choice")
    if (
        isinstance(correct_choice, int)
        and 0 <= correct_choice < len(choices)
        and isinstance(correct_answer, str)
        and choices[correct_choice] == correct_answer
    ):
        chosen = correct_choice
    elif isinstance(correct_answer, str) and correct_answer in choices:
        chosen = choices.index(correct_answer)
    else:
        if isinstance(correct_choice, int) and 0 <= correct_choice < len(choices):
            chosen = correct_choice
    if chosen < 0:
        return None

    explanation = str(question.get("explanation") or "").strip()
    explanation_steps = _split_explanation(explanation)
    concepts = [str(tag) for tag in question.get("concept_tags", [])]
    if not concepts:
        concepts = [str(question.get("unit", "known_solution"))]

    return ReasonedTrace(
        rule_id="known_solution_bank",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {choices[chosen]}",
        signals=_stem_signals(question.get("stem", "")) or [
            "검수 풀이 데이터가 존재하는 기출/학습 문항",
            f"과목={question.get('subject')}, 단원={question.get('unit')}",
        ],
        concepts=concepts,
        formula_steps=[
            "지원 계산 규칙에 직접 매칭되지는 않아 검수 풀이 데이터 기반으로 재구성한다.",
            *explanation_steps,
        ],
        choice_notes=[
            (
                f"{idx + 1}번 {choice}: 검수 풀이 데이터의 확정 답안"
                if idx == chosen
                else f"{idx + 1}번 {choice}: 검수 풀이 데이터의 답안과 달라 제거"
            )
            for idx, choice in enumerate(choices)
        ],
        computed_value=_first_money_value(choices[chosen]),
        confidence=_review_confidence(str(question.get("review_status", ""))),
    )


def _split_explanation(explanation: str) -> list[str]:
    if not explanation:
        return ["검수 해설 본문이 없어 정답키와 선택지 대응만 사용한다."]
    parts = [
        part.strip(" -\t")
        for part in re.split(r"[\r\n]+|(?<=[.!?。])\s+", explanation)
        if part.strip(" -\t")
    ]
    return parts[:5]


def _review_confidence(review_status: str) -> float:
    if "expert" in review_status:
        return 0.95
    if "verified" in review_status or "revised" in review_status:
        return 0.86
    return 0.72


def _solve_npv(question: dict[str, Any]) -> ReasonedTrace | None:
    stem = question.get("stem", "")
    if "NPV" not in stem and "순현재가치" not in stem:
        return None
    rate_match = re.search(r"할인율이?\s*연?\s*([0-9.]+)%", stem)
    flows = [(int(y), _parse_number(v)) for y, v in re.findall(r"(\d+)년\s*뒤\s*([0-9,]+)원", stem)]
    initial_match = re.search(r"오늘\s*([0-9,]+)원을?\s*투자", stem)
    if not rate_match or not flows or not initial_match:
        return None

    rate = float(rate_match.group(1)) / 100
    initial = _parse_number(initial_match.group(1))
    present_values = [(year, cash / ((1 + rate) ** year)) for year, cash in flows]
    value = -initial + sum(pv for _, pv in present_values)
    value = math.floor(value) if "절사" in stem else round(value)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    return ReasonedTrace(
        rule_id="finance_npv",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["순현재가치/NPV", "오늘 투자액", "연도별 미래 현금흐름", "할인율"],
        concepts=["화폐의 시간가치", "현금흐름 할인", "NPV = 미래현금흐름 현재가치 - 초기투자"],
        formula_steps=[
            f"초기투자 = {initial:,.0f}원",
            *[
                f"{year}년 뒤 현금흐름 현재가치 = {cash_pv:,.0f}원"
                for year, cash_pv in present_values
            ],
            f"NPV = -{initial:,.0f} + 현재가치 합계 = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.92,
    )


def _solve_moving_average_inventory(question: dict[str, Any]) -> ReasonedTrace | None:
    stem = question.get("stem", "")
    if "이동평균법" not in stem or "기말재고" not in stem:
        return None
    initial = re.search(r"기초재고\s*(\d+)개\(@([0-9,]+)\)", stem)
    purchases = re.findall(r"(\d+)차\s*매입\s*(\d+)개\(@([0-9,]+)\)", stem)
    sale = re.search(r"1차\s*매입\s*후\s*(\d+)개를?\s*판매", stem)
    ending = re.search(r"기말재고\s*수량\s*(\d+)개", stem)
    if not initial or len(purchases) < 2 or not sale or not ending:
        return None

    initial_qty = int(initial.group(1))
    initial_cost = _parse_number(initial.group(2))
    first_qty = int(purchases[0][1])
    first_cost = _parse_number(purchases[0][2])
    second_qty = int(purchases[1][1])
    second_cost = _parse_number(purchases[1][2])
    sold_qty = int(sale.group(1))
    ending_qty = int(ending.group(1))

    first_pool_cost = initial_qty * initial_cost + first_qty * first_cost
    first_pool_qty = initial_qty + first_qty
    first_average = first_pool_cost / first_pool_qty
    remaining_qty = first_pool_qty - sold_qty
    remaining_cost = remaining_qty * first_average
    final_cost = remaining_cost + second_qty * second_cost
    final_qty = remaining_qty + second_qty
    if final_qty != ending_qty:
        return None

    value = round(final_cost)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    return ReasonedTrace(
        rule_id="accounting_moving_average_inventory",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["이동평균법", "1차 매입 후 판매", "2차 매입 후 기말수량"],
        concepts=["판매 시점 전후 평균단가 재계산", "기말재고 = 남은 수량의 장부원가"],
        formula_steps=[
            f"1차 매입 후 평균단가 = {first_pool_cost:,.0f} / {first_pool_qty} = {first_average:,.2f}원",
            f"판매 후 잔량 {remaining_qty}개 원가 = {remaining_cost:,.0f}원",
            f"2차 매입 후 총원가 = {remaining_cost:,.0f} + {second_qty}×{second_cost:,.0f} = {value:,.0f}원",
            f"기말수량 {ending_qty}개와 일치하므로 기말재고 = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.94,
    )


def _solve_effective_interest(question: dict[str, Any]) -> ReasonedTrace | None:
    stem = question.get("stem", "")
    if "유효이자율" not in stem or "이자수익" not in stem:
        return None
    book_match = re.search(r"([0-9,]+)원에\s*취득", stem)
    rate_match = re.search(r"유효이자율은?\s*연?\s*([0-9.]+)%", stem)
    if not book_match or not rate_match:
        return None

    book_value = _parse_number(book_match.group(1))
    rate = float(rate_match.group(1)) / 100
    value = math.floor(book_value * rate) if "절사" in stem else round(book_value * rate)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    return ReasonedTrace(
        rule_id="accounting_effective_interest",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["상각후원가 금융자산", "유효이자율", "이자수익"],
        concepts=["유효이자율법", "이자수익 = 기초 장부금액 × 유효이자율"],
        formula_steps=[
            f"기초 장부금액 = {book_value:,.0f}원",
            f"유효이자율 = {rate:.1%}",
            f"이자수익 = {book_value:,.0f} × {rate:.1%} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.93,
    )


def _solve_gordon_growth(question: dict[str, Any]) -> ReasonedTrace | None:
    stem = question.get("stem", "")
    if "고든" not in stem or "EPS" not in stem:
        return None
    eps_match = re.search(r"EPS(?:는|가)?\s*([0-9,]+)원", stem)
    payout_match = re.search(r"배당성향(?:은|이)?\s*([0-9.]+)%", stem)
    roe_match = re.search(r"ROE\)?(?:은|이)?\s*([0-9.]+)%", stem)
    required_match = re.search(r"요구수익률(?:은|이)?\s*([0-9.]+)%", stem)
    if not all([eps_match, payout_match, roe_match, required_match]):
        return None

    eps = _parse_number(eps_match.group(1))
    payout = float(payout_match.group(1)) / 100
    roe = float(roe_match.group(1)) / 100
    required = float(required_match.group(1)) / 100
    retention = 1 - payout
    growth = retention * roe
    if required <= growth:
        return None
    dividend = eps * payout
    value = round(dividend / (required - growth))
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    return ReasonedTrace(
        rule_id="finance_gordon_growth",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["고든 성장모형", "EPS", "배당성향", "ROE", "요구수익률"],
        concepts=["지속가능성장률 = 유보율 × ROE", "P0 = D1 / (k - g)"],
        formula_steps=[
            f"유보율 = 1 - {payout:.1%} = {retention:.1%}",
            f"성장률 g = {retention:.1%} × {roe:.1%} = {growth:.1%}",
            f"D1 = {eps:,.0f} × {payout:.1%} = {dividend:,.0f}원",
            f"P0 = {dividend:,.0f} / ({required:.1%} - {growth:.1%}) = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.91,
    )


def _solve_revaluation_loss(question: dict[str, Any]) -> ReasonedTrace | None:
    stem = question.get("stem", "")
    if "재평가모형" not in stem or "재평가손실" not in stem:
        return None
    if "이익잉여금으로 대체한다" in stem and "대체하지 않는다" not in stem:
        return None
    money_values = _money_values(stem)
    life_match = re.search(r"내용연수\s*(\d+)년", stem)
    if len(money_values) < 4 or not life_match:
        return None

    cost = money_values[0]
    residual = money_values[1]
    fair_value_1 = money_values[-2]
    fair_value_2 = money_values[-1]
    life = int(life_match.group(1))
    first_depr = (cost - residual) / life
    carrying_before_first_revaluation = cost - first_depr
    surplus = max(0.0, fair_value_1 - carrying_before_first_revaluation)
    second_depr = fair_value_1 / (life - 1)
    carrying_before_second_revaluation = fair_value_1 - second_depr
    decrease = carrying_before_second_revaluation - fair_value_2
    value = round(max(0.0, decrease - surplus))
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    return ReasonedTrace(
        rule_id="accounting_revaluation_loss",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["재평가모형", "감가상각누계액 제거", "재평가손실", "잉여금 대체 없음"],
        concepts=["재평가증가분은 OCI", "이후 감소분은 기존 재평가잉여금 먼저 차감", "초과 감소분은 당기손익"],
        formula_steps=[
            f"1차 감가상각비 = ({cost:,.0f} - {residual:,.0f}) / {life} = {first_depr:,.0f}원",
            f"1차 재평가잉여금 = {fair_value_1:,.0f} - {carrying_before_first_revaluation:,.0f} = {surplus:,.0f}원",
            f"2차 감가상각비 = {fair_value_1:,.0f} / {life - 1} = {second_depr:,.0f}원",
            f"2차 감소액 = {carrying_before_second_revaluation:,.0f} - {fair_value_2:,.0f} = {decrease:,.0f}원",
            f"당기손익 손실 = {decrease:,.0f} - {surplus:,.0f} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.9,
    )


def _solve_corporate_tax(question: dict[str, Any]) -> ReasonedTrace | None:
    stem = question.get("stem", "")
    if "법인세율" not in stem or "산출세액" not in stem:
        return None

    base = _extract_tax_base(stem)
    if base is None:
        return None
    value = round(_corporate_tax_2026(base))
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    formula_steps = [f"과세표준 = {base:,.0f}원"]
    if base <= 200_000_000:
        formula_steps.append(f"산출세액 = {base:,.0f} × 9% = {value:,.0f}원")
    else:
        excess = min(base, 20_000_000_000) - 200_000_000
        formula_steps.append(
            f"산출세액 = 200,000,000×9% + {excess:,.0f}×19% = {value:,.0f}원"
        )

    return ReasonedTrace(
        rule_id="tax_corporate_progressive_rate",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["산출세액", "법인세율", "과세표준 또는 과세표준 계산 자료"],
        concepts=["과세표준 계산", "초과누진세율", "법인세 산출세액"],
        formula_steps=formula_steps,
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.88,
    )


def _extract_tax_base(stem: str) -> float | None:
    direct = re.search(r"과세표준(?:이|은)\s*([0-9,]+)원", stem)
    if direct:
        return _parse_number(direct.group(1))

    income = _money_after(stem, "각사업연도소득금액")
    if income is None:
        return None
    tax_exempt = _money_after(stem, "비과세소득") or 0.0
    loss = _money_after(stem, "이월결손금") or 0.0
    deduction = _money_after(stem, "소득공제") or 0.0
    loss_limit = income * 0.8 if "80%" in stem or "일반결손금" in stem else loss
    deductible_loss = min(loss, loss_limit)
    return income - deductible_loss - tax_exempt - deduction


def _corporate_tax_2026(base: float) -> float:
    tax = min(base, 200_000_000) * 0.09
    if base > 200_000_000:
        tax += (min(base, 20_000_000_000) - 200_000_000) * 0.19
    if base > 20_000_000_000:
        tax += (min(base, 300_000_000_000) - 20_000_000_000) * 0.21
    if base > 300_000_000_000:
        tax += (base - 300_000_000_000) * 0.24
    return tax


def _stem_signals(stem: str) -> list[str]:
    candidates = [
        "순현재가치",
        "NPV",
        "이동평균법",
        "유효이자율",
        "고든 성장모형",
        "재평가모형",
        "법인세율",
        "산출세액",
    ]
    return [signal for signal in candidates if signal in stem]


def _choice_notes(choices: list[str], chosen_index: int, computed_value: float) -> list[str]:
    notes: list[str] = []
    for idx, choice in enumerate(choices):
        value = _first_money_value(choice)
        if value is None:
            notes.append(f"{idx + 1}번 {choice}: 금액 비교 불가")
            continue
        diff = abs(value - computed_value)
        if idx == chosen_index:
            notes.append(f"{idx + 1}번 {choice}: 계산값 {computed_value:,.0f}원과 가장 일치")
        else:
            notes.append(f"{idx + 1}번 {choice}: 계산값과 {diff:,.0f}원 차이로 제거")
    return notes


def _choose_closest_money(choices: list[str], target: float) -> int:
    values = [_first_money_value(choice) for choice in choices]
    indexed = [(idx, value) for idx, value in enumerate(values) if value is not None]
    if not indexed:
        return -1
    return min(indexed, key=lambda item: abs(item[1] - target))[0]


def _first_money_value(text: str) -> float | None:
    values = _money_values(text)
    return values[0] if values else None


def _money_values(text: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(r"(?:₩\s*)?([0-9][0-9,]*(?:\.\d+)?)\s*(억\s*원|억원|원)?", text):
        unit = (match.group(2) or "").replace(" ", "")
        if unit in {"억원", "억원"}:
            values.append(_parse_number(match.group(1)) * 100_000_000)
        elif unit == "원" or match.group(0).strip().startswith("₩"):
            values.append(_parse_number(match.group(1)))
    return values


def _money_after(stem: str, label: str) -> float | None:
    start = stem.find(label)
    if start < 0:
        return None
    window = stem[start + len(label): start + len(label) + 120]
    match = re.search(r"([0-9][0-9,]*)원", window)
    return _parse_number(match.group(1)) if match else None


def _parse_number(value: str) -> float:
    return float(value.replace(",", ""))


_RULES: tuple[Rule, ...] = (
    _solve_npv,
    _solve_moving_average_inventory,
    _solve_effective_interest,
    _solve_gordon_growth,
    _solve_revaluation_loss,
    _solve_corporate_tax,
)
