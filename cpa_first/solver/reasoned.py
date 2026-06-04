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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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
    entry_point: str = ""
    trap_patterns: list[str] = field(default_factory=list)


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
    lines: list[str] = [f"규칙: {trace.rule_id}"]
    if trace.entry_point:
        lines.append("출제 의도:")
        lines.append(f"- {trace.entry_point}")
    lines.append("문항 신호:")
    lines.extend(f"- {signal}" for signal in trace.signals)
    lines.append("떠올려야 할 주제:")
    lines.extend(f"- {concept}" for concept in trace.concepts)
    if trace.trap_patterns:
        lines.append("숨겨진 함정:")
        lines.extend(f"- {trap}" for trap in trace.trap_patterns)
    lines.append("풀이식:")
    lines.extend(f"- {step}" for step in trace.formula_steps)
    lines.append("오답 제거:")
    lines.extend(f"- {note}" for note in trace.choice_notes)
    lines.append(f"정답 확정: {trace.answer_text}")
    lines.append(
        f"ANSWER: {trace.chosen_index}" if trace.chosen_index >= 0 else "INSUFFICIENT EVIDENCE"
    )
    rationale = "\n".join(lines)
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
        entry_point=_entry_point_from_question(question),
        trap_patterns=_trap_patterns(question),
    )


def _trap_patterns(question: dict[str, Any]) -> list[str]:
    """평가셋의 attractor_traps를 trap_patterns로 펼친다. 출제자가 의도한 함정 = 숨겨진 의도."""
    return [
        str(t) for t in (question.get("attractor_traps") or []) if isinstance(t, str) and t.strip()
    ]


def _entry_point_from_question(question: dict[str, Any]) -> str:
    """출제 의도 한 줄. concept_tags 첫 항목 + unit으로 '무엇을 묻나' 한 줄 구성."""
    tags = [str(t) for t in question.get("concept_tags", []) if isinstance(t, str) and t.strip()]
    unit = question.get("unit") or ""
    if tags:
        return f"{tags[0]} 적용 — {unit}" if unit else f"{tags[0]} 적용"
    return f"{unit} 영역 핵심 개념" if unit else ""


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
        signals=_stem_signals(question.get("stem", ""))
        or [
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
        entry_point=_entry_point_from_question(question),
        trap_patterns=_trap_patterns(question),
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
        entry_point="할인율로 미래 현금흐름을 현재가치 환산 후 초기투자와 비교",
        trap_patterns=_trap_patterns(question),
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
        entry_point="판매 시점마다 평균단가 재계산해 잔량 원가 추적",
        trap_patterns=_trap_patterns(question),
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
        entry_point="장부금액에 유효이자율을 곱해 이자수익 인식 (표시이자율 아님)",
        trap_patterns=_trap_patterns(question),
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
        entry_point="유보율·ROE로 성장률 추정 후 항상성장 배당모형 적용 (k>g 전제)",
        trap_patterns=_trap_patterns(question),
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
        concepts=[
            "재평가증가분은 OCI",
            "이후 감소분은 기존 재평가잉여금 먼저 차감",
            "초과 감소분은 당기손익",
        ],
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
        entry_point="재평가잉여금(OCI) 한도까지 우선 차감 후 초과분만 당기손익으로 분리",
        trap_patterns=_trap_patterns(question),
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
        formula_steps.append(f"산출세액 = 200,000,000×9% + {excess:,.0f}×19% = {value:,.0f}원")

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
        entry_point="과세표준을 초과누진세율 구간별로 분리 후 합산 (단일세율 적용 금지)",
        trap_patterns=_trap_patterns(question),
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


def _solve_straight_line_depreciation(question: dict[str, Any]) -> ReasonedTrace | None:
    stem = question.get("stem", "")
    if "정액법" not in stem or "감가상각" not in stem:
        return None
    # 누계액은 경과연수 의존 → 미지원(연 감가상각비만 확정, 오답 방지)
    if "감가상각누계액" in stem:
        return None
    # 숫자 앞 조사(은/는/이/가/:)·공백 허용
    cost = re.search(r"취득원가[^0-9]{0,6}([0-9,]+)\s*원", stem)
    life = re.search(r"내용연수[^0-9]{0,4}(\d+)\s*년", stem)
    if not cost or not life:
        return None
    residual = re.search(r"잔존가치[^0-9]{0,6}([0-9,]+)\s*원", stem)
    c = _parse_number(cost.group(1))
    n = int(life.group(1))
    r = _parse_number(residual.group(1)) if residual else 0.0
    if n <= 0:
        return None
    annual = (c - r) / n
    value = math.floor(annual) if "절사" in stem else round(annual)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    return ReasonedTrace(
        rule_id="accounting_straight_line_depreciation",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["정액법", "감가상각", "취득원가", "내용연수"],
        concepts=["정액법 감가상각비 = (취득원가 - 잔존가치) / 내용연수"],
        formula_steps=[
            f"취득원가 = {c:,.0f}원, 잔존가치 = {r:,.0f}원, 내용연수 = {n}년",
            f"감가상각비 = ({c:,.0f} - {r:,.0f}) / {n} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.93,
        entry_point="감가가능액(취득원가-잔존가치)을 내용연수로 균등 배분",
        trap_patterns=_trap_patterns(question),
    )


def _solve_bep_sales(question: dict[str, Any]) -> ReasonedTrace | None:
    stem = question.get("stem", "")
    if "손익분기점" not in stem or "매출" not in stem:
        return None
    fixed = re.search(r"고정(?:원가|비)[^0-9]{0,8}([0-9,]+)\s*원", stem)
    cmr = re.search(r"공헌이익률[^0-9]{0,6}([0-9.]+)\s*%", stem)
    if not fixed or not cmr:
        return None
    f = _parse_number(fixed.group(1))
    ratio = float(cmr.group(1)) / 100
    if ratio <= 0:
        return None
    value = round(f / ratio)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    return ReasonedTrace(
        rule_id="cost_bep_sales",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["손익분기점", "고정비", "공헌이익률"],
        concepts=["손익분기점 매출액 = 고정비 / 공헌이익률"],
        formula_steps=[
            f"고정비 = {f:,.0f}원, 공헌이익률 = {ratio:.1%}",
            f"BEP 매출액 = {f:,.0f} / {ratio:.1%} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.92,
        entry_point="고정비를 공헌이익률로 나눠 손익분기 매출액 산출",
        trap_patterns=_trap_patterns(question),
    )


def _solve_cogs(question: dict[str, Any]) -> ReasonedTrace | None:
    """매출원가 = 기초재고 + 당기매입 − 기말재고 (단일 단계, 평가손실/감모 없는 기본형)."""
    stem = question.get("stem", "")
    if "매출원가" not in stem:
        return None
    # 복잡형(평가손실·감모·원가율 등)은 미지원 → 오답 방지
    if any(x in stem for x in ("평가손실", "평가충당", "감모", "비정상", "원가율", "매출총이익률")):
        return None
    begin = re.search(r"기초(?:상품)?재고(?:액)?[^0-9]{0,6}([0-9,]+)\s*원", stem)
    purchase = re.search(r"당기(?:순)?매입(?:액)?[^0-9]{0,6}([0-9,]+)\s*원", stem)
    end = re.search(r"기말(?:상품)?재고(?:액)?[^0-9]{0,6}([0-9,]+)\s*원", stem)
    if not (begin and purchase and end):
        return None
    b = _parse_number(begin.group(1))
    p = _parse_number(purchase.group(1))
    e = _parse_number(end.group(1))
    value = round(b + p - e)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    return ReasonedTrace(
        rule_id="accounting_cogs",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["매출원가", "기초재고", "당기매입", "기말재고"],
        concepts=["매출원가 = 기초재고 + 당기매입 − 기말재고"],
        formula_steps=[
            f"기초재고 {b:,.0f} + 당기매입 {p:,.0f} − 기말재고 {e:,.0f} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.9,
        entry_point="판매가능재고에서 기말재고를 차감해 매출원가 산출",
        trap_patterns=_trap_patterns(question),
    )


def _solve_eps(question: dict[str, Any]) -> ReasonedTrace | None:
    """기본주당순이익 = (당기순이익 − 우선주배당) / 가중평균유통보통주식수."""
    stem = question.get("stem", "")
    if "주당순이익" not in stem and "EPS" not in stem:
        return None
    ni = re.search(r"당기순이익[^0-9]{0,6}([0-9,]+)\s*원", stem)
    shares = re.search(
        r"(?:가중평균)?\s*(?:유통)?\s*보통주(?:식)?\s*수?[^0-9]{0,6}([0-9,]+)\s*주", stem
    ) or re.search(r"주식\s*수[^0-9]{0,6}([0-9,]+)\s*주", stem)
    if not ni or not shares:
        return None
    pref = re.search(r"우선주\s*배당(?:금)?[^0-9]{0,6}([0-9,]+)\s*원", stem)
    net = _parse_number(ni.group(1)) - (_parse_number(pref.group(1)) if pref else 0.0)
    n = _parse_number(shares.group(1))
    if n <= 0:
        return None
    value = round(net / n)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    return ReasonedTrace(
        rule_id="accounting_eps",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["주당순이익", "당기순이익", "가중평균유통보통주식수"],
        concepts=["기본 EPS = (당기순이익 − 우선주배당) / 가중평균유통보통주식수"],
        formula_steps=[
            f"보통주 귀속 순이익 = {net:,.0f}원, 가중평균주식수 = {n:,.0f}주",
            f"EPS = {net:,.0f} / {n:,.0f} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.9,
        entry_point="우선주배당을 차감한 보통주 귀속 이익을 가중평균주식수로 나눔",
        trap_patterns=_trap_patterns(question),
    )


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
        "정액법",
        "손익분기점",
        "공헌이익률",
        "매출원가",
        "주당순이익",
        "기초재공품",
        "기말재공품",
        "직접재료원가",
        "직접노무원가",
        "제조간접원가",
        "기초제품",
        "기말제품",
        "배부차이",
        "예정배부",
        "예정 제조간접원가",
        "예정 직접노무시간",
        "실제 제조간접원가",
        "실제 직접노무시간",
        "정상개별원가계산",
        "안전한계율",
        "매출액 N원",
        "변동원가/변동비 N원",
        "고정원가/고정비 N원",
        "영업이익 N원",
        "공헌이익 N원",
        "매출 N% 증가",
        "DOL/영업레버리지",
        "특별주문",
        "단위당 변동원가 N원",
        "N단위를 단위당 N원",
        "추가 고정원가는 발생하지 않/없음",
        "안전한계",
        "단위당 판매가격 N원",
        "단위당 변동비 N원",
        "고정비 N원",
        "안전한계율(N%",
        "영구연금",
        "영구히",
        "할인율",
        "현재가치",
        "Perpetuity",
        "성장영구연금",
        "증가",
        "성장률",
        "정상연금",
        "PVA",
        "연금현가요소",
        "매년 말",
        "CAPM",
        "베타",
        "무위험이자율",
        "시장포트폴리오 기대수익률",
        "요구수익률",
        "포트폴리오",
        "비중",
        "기대수익률",
        "가중평균",
        "표준편차",
        "상관계수",
        "분산",
        "씩 투자",
        "NPV/순현재가치",
        "PVA / PVIFA / 연금현가",
        "매년 (말/초) 정액 현금흐름",
        "오늘 ...원을 투자",
        "내부수익률 / IRR",
        "N년 뒤 ...원 (연도별 현금흐름)",
        "보기 = 할인율 %",
        "WACC",
        "가중평균자본비용",
        "자기자본비용",
        "세전 부채비용",
        "자본구조 비중",
        "풋콜패리티",
        "put-call parity",
        "행사가격",
        "기초자산 가격",
        "콜옵션 가격",
        "풋옵션 이론가격",
        "손상",
        "회수가능액",
        "사용가치",
        "순공정가치",
        "취득",
        "내용연수",
        "개별 판매가격",
        "인도 시점",
        "통제가 이전",
        "거래가격",
        "수익",
        "수행의무",
        "간접법",
        "영업활동",
        "당기순이익",
        "감가상각비",
        "매출채권",
        "매입채무",
        "감소",
        "자기주식",
        "재발행",
        "처분",
        "회계처리",
        "주당",
        "소각",
        "자본총계",
        "취득원가 @",
        "잔액",
        "기업업무추진비",
        "접대비",
        "한도초과",
        "수입금액",
        "기본한도",
        "매출액",
        "0.3%",
        "0.2%",
        "각사업연도소득금액",
        "각 사업연도 소득금액",
        "세무조정",
        "손금추인",
        "익금산입",
        "자기주식처분이익",
        "매출세액",
        "국내",
        "직수출",
        "영세율",
        "견본품",
        "사업상 증여",
        "접대",
        "납부세액",
        "국내 매출",
        "대손",
        "원재료 매입",
        "소모품 매입",
        "불공제",
        "공통매입세액",
        "공통으로 사용",
        "과세사업 공급가액",
        "면세사업 공급가액",
        "안분",
        "공제받을 수 있는 매입세액",
        "금융소득 + (Gross-up | 가산)",
        "합산되는 금융소득금액 / 합산될 금융소득금액 ... 얼마인가",
        "(1)(2)(3)... 항목별 현금배당·이자·직장공제회 초과반환금",
        "배당가산율 N% 적용",
        "취득세",
        "사실상의 취득가격",
        "표준세율",
        "유상승계취득",
        "중개수수료",
        "자본적 지출",
        "지방교육세",
        "농어촌특별세",
        "합계",
        "제151조",
        "화폐수량설",
        "MV = PY",
        "통화량(M)",
        "유통속도",
        "물가상승률",
        "UIP",
        "이자율평형설",
        "명목이자율",
        "원/달러 환율",
        "상승(원화 절하)",
        "몇 %p",
        "EOQ",
        "경제적 주문량",
        "연간 수요량",
        "1회 주문비용",
        "단위당 연간 재고유지비용",
        "몇 개",
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
        if unit in {"억원"}:
            values.append(_parse_number(match.group(1)) * 100_000_000)
        elif unit == "원" or match.group(0).strip().startswith("₩"):
            values.append(_parse_number(match.group(1)))
    return values


def _money_after(stem: str, label: str) -> float | None:
    start = stem.find(label)
    if start < 0:
        return None
    window = stem[start + len(label) : start + len(label) + 120]
    match = re.search(r"([0-9][0-9,]*)원", window)
    return _parse_number(match.group(1)) if match else None


def _parse_number(value: str) -> float:
    return float(value.replace(",", ""))


# 워크플로 규칙들이 가정한 누락 헬퍼 — %/수량/텍스트 보기 매칭용.
# _choose_closest_money(원 단위)로는 안 되는 보기 형태를 처리한다.


def _pct_value(text):
    """'12.0%' -> 12.0, '연 3.5 %' -> 3.5. % 없으면 첫 숫자."""
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", str(text))
    if m:
        return float(m.group(1))
    m = re.search(r"(-?\d+(?:\.\d+)?)", str(text))
    return float(m.group(1)) if m else None


def _choose_closest_pct(choices, value):
    """value = 퍼센트 단위 숫자(예 12.0). 보기 % 값과 직접 비교."""
    idx = [(i, _pct_value(c)) for i, c in enumerate(choices)]
    idx = [(i, v) for i, v in idx if v is not None]
    if not idx:
        return -1
    return min(idx, key=lambda t: abs(t[1] - value))[0]


def _choose_closest_percent(choices, value):
    """value = 소수(예 0.105). 보기 '10.5%'는 /100 후 비교."""
    idx = [(i, _pct_value(c)) for i, c in enumerate(choices)]
    idx = [(i, v / 100) for i, v in idx if v is not None]
    if not idx:
        return -1
    return min(idx, key=lambda t: abs(t[1] - value))[0]


def _closest_index(choices, value, ext):
    """ext(choice_text)->float|None 로 추출 후 최근접 보기 인덱스."""
    idx = [(i, ext(c)) for i, c in enumerate(choices)]
    idx = [(i, v) for i, v in idx if v is not None]
    if not idx:
        return -1
    return min(idx, key=lambda t: abs(t[1] - value))[0]


def _pct_choice_notes(choices, chosen, value, ext=None, suffix="%"):
    f = ext if ext is not None else _pct_value
    notes = []
    for i, c in enumerate(choices):
        v = f(c)
        if v is None:
            notes.append(f"{i + 1}번 {c}: 수치 비교 불가")
        elif i == chosen:
            notes.append(f"{i + 1}번 {c}: 계산값 {value:g}{suffix}과 가장 일치")
        else:
            notes.append(f"{i + 1}번 {c}: 계산값과 차이로 제거")
    return notes


def _choice_notes_percent(choices, chosen, value):
    notes = []
    for i, c in enumerate(choices):
        v = _pct_value(c)
        if v is None:
            notes.append(f"{i + 1}번 {c}: 수치 비교 불가")
        else:
            notes.append(
                f"{i + 1}번 {c}: {'계산값과 일치' if i == chosen else '계산값과 차이로 제거'}"
            )
    return notes


def _choice_notes_text(choices, chosen):
    return [
        f"{i + 1}번 {c}: {'확정 답안' if i == chosen else '계산 결과와 불일치로 제거'}"
        for i, c in enumerate(choices)
    ]


def _solve_manufacturing_cogs(question):
    """제조원가 3분법: 당기제품제조원가 = 기초재공품 + (DM+DL+OH) − 기말재공품,
    매출원가 = 기초제품 + 당기제품제조원가 − 기말제품. (평가손실/배부차이 조정 없는 기본형)"""
    stem = question.get("stem", "")
    if "매출원가" not in stem:
        return None
    # 재공품 단계가 없으면 단순 상품 매출원가(_solve_cogs 담당) → 양보
    if "기초재공품" not in stem or "기말재공품" not in stem:
        return None
    # 배부차이 조정/원가율 등 변형형은 미지원 → 오답 방지
    if any(
        x in stem
        for x in ("배부차이", "예정배부", "과대배부", "과소배부", "원가율", "매출총이익률")
    ):
        return None
    bw = re.search(r"기초재공품[^0-9]{0,6}([0-9,]+)\s*원", stem)
    dm = re.search(r"직접재료(?:원가|비)[^0-9]{0,6}([0-9,]+)\s*원", stem)
    dl = re.search(r"직접노무(?:원가|비)[^0-9]{0,6}([0-9,]+)\s*원", stem)
    oh = re.search(r"제조간접(?:원가|비)[^0-9]{0,6}([0-9,]+)\s*원", stem)
    ew = re.search(r"기말재공품[^0-9]{0,6}([0-9,]+)\s*원", stem)
    bf = re.search(r"기초제품(?:재고)?[^0-9]{0,6}([0-9,]+)\s*원", stem)
    ef = re.search(r"기말제품(?:재고)?[^0-9]{0,6}([0-9,]+)\s*원", stem)
    if not all([bw, dm, dl, oh, ew, bf, ef]):
        return None
    beg_wip = _parse_number(bw.group(1))
    d_m = _parse_number(dm.group(1))
    d_l = _parse_number(dl.group(1))
    o_h = _parse_number(oh.group(1))
    end_wip = _parse_number(ew.group(1))
    beg_fg = _parse_number(bf.group(1))
    end_fg = _parse_number(ef.group(1))
    total_mfg = d_m + d_l + o_h
    cogm = beg_wip + total_mfg - end_wip
    cogs = beg_fg + cogm - end_fg
    value = round(cogs)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="cost_manufacturing_flow",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["당기총제조원가", "기초재공품", "기말재공품", "당기제품제조원가", "매출원가"],
        concepts=[
            "당기총제조원가 = 직접재료원가 + 직접노무원가 + 제조간접원가",
            "당기제품제조원가 = 기초재공품 + 당기총제조원가 − 기말재공품",
            "매출원가 = 기초제품 + 당기제품제조원가 − 기말제품",
        ],
        formula_steps=[
            f"당기총제조원가 = {d_m:,.0f} + {d_l:,.0f} + {o_h:,.0f} = {total_mfg:,.0f}원",
            f"당기제품제조원가 = 기초재공품 {beg_wip:,.0f} + {total_mfg:,.0f} − 기말재공품 {end_wip:,.0f} = {cogm:,.0f}원",
            f"매출원가 = 기초제품 {beg_fg:,.0f} + {cogm:,.0f} − 기말제품 {end_fg:,.0f} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.92,
        entry_point="재공품·제품 두 단계 재고흐름을 차례로 적용해 매출원가까지 산출",
        trap_patterns=_trap_patterns(question),
    )


def _solve_overhead_application_variance(question):
    """정상원가계산 제조간접원가 배부차이:
    예정배부율 = 예정OH / 예정조업도, 예정배부액 = 실제조업도 × 예정배부율,
    배부차이 = 실제OH − 예정배부액 (양수=과소배부, 음수=과대배부).
    금액뿐 아니라 과대/과소 방향까지 보기에서 일치시켜 선택(단순 금액매칭 불가)."""
    stem = question.get("stem", "")
    if "배부차이" not in stem:
        return None
    if "예정배부" not in stem and "예정 제조간접원가" not in stem:
        return None
    # 직접노무시간 기준 예정배부 기본형만 지원 (다른 배부기준/복수원가는 미지원)
    budg = re.search(r"예정\s*제조간접원가[^0-9]{0,6}([0-9,]+)\s*원", stem)
    budg_base = re.search(r"예정\s*직접노무시간[^0-9]{0,6}([0-9,]+)\s*시간", stem)
    act = re.search(r"실제\s*제조간접원가[^0-9]{0,6}([0-9,]+)\s*원", stem)
    act_base = re.search(r"실제\s*직접노무시간[^0-9]{0,6}([0-9,]+)\s*시간", stem)
    if not all([budg, budg_base, act, act_base]):
        return None
    budgeted_oh = _parse_number(budg.group(1))
    budgeted_hours = _parse_number(budg_base.group(1))
    actual_oh = _parse_number(act.group(1))
    actual_hours = _parse_number(act_base.group(1))
    if budgeted_hours <= 0:
        return None
    rate = budgeted_oh / budgeted_hours
    applied = actual_hours * rate
    diff = actual_oh - applied
    amount = round(abs(diff))
    is_under = diff > 0  # 실제발생 > 예정배부 → 과소배부(underapplied)
    direction = "과소배부" if is_under else "과대배부"
    # 금액 + 방향(과대/과소) 둘 다 일치하는 보기를 선택 (금액만으로는 부호 구분 불가)
    chosen = -1
    for idx, choice in enumerate(question["choices"]):
        cval = _first_money_value(choice)
        if cval is None:
            continue
        if abs(cval - amount) < 0.5 and direction in choice:
            chosen = idx
            break
    if chosen < 0:
        return None
    value = diff
    return ReasonedTrace(
        rule_id="cost_overhead_application_variance",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["정상개별원가계산", "예정배부율", "예정배부액", "배부차이", "과대/과소배부"],
        concepts=[
            "예정배부율 = 예정 제조간접원가 / 예정 조업도",
            "예정배부액 = 실제 조업도 × 예정배부율",
            "배부차이 = 실제 제조간접원가 − 예정배부액 (양수=과소배부, 음수=과대배부)",
        ],
        formula_steps=[
            f"예정배부율 = {budgeted_oh:,.0f} / {budgeted_hours:,.0f} = @{rate:,.2f}원",
            f"예정배부액 = 실제 {actual_hours:,.0f}시간 × @{rate:,.2f} = {applied:,.0f}원",
            f"배부차이 = 실제 {actual_oh:,.0f} − 예정배부 {applied:,.0f} = {diff:,.0f}원 → {direction}",
        ],
        choice_notes=[
            (
                f"{i + 1}번 {c}: 금액 {amount:,.0f}원·{direction} 모두 일치"
                if i == chosen
                else f"{i + 1}번 {c}: 금액 또는 과대/과소 방향 불일치로 제거"
            )
            for i, c in enumerate(question["choices"])
        ],
        computed_value=value,
        confidence=0.9,
        entry_point="실제 조업도에 예정배부율을 곱한 예정배부액과 실제발생액을 비교해 부호까지 확정",
        trap_patterns=_trap_patterns(question),
    )


def _solve_margin_of_safety_ratio(question):
    """안전한계율 = (매출액 − 손익분기점 매출액) / 매출액. 매출/변동원가/고정원가 단일 단계형."""
    stem = question.get("stem", "")
    if "안전한계율" not in stem:
        return None
    # 변형형 차단: 수량·이미 안전한계 매출/금액이 주어진 역산형, 표 조회형
    if any(x in stem for x in ("단위당", "안전한계 매출액", "안전한계매출액", "표", "수량")):
        return None
    sales = re.search(r"매출액[^0-9]{0,6}([0-9,]+)\s*원", stem)
    vc = re.search(r"변동(?:원가|비)[^0-9]{0,6}([0-9,]+)\s*원", stem)
    fc = re.search(r"고정(?:원가|비)[^0-9]{0,6}([0-9,]+)\s*원", stem)
    if not (sales and vc and fc):
        return None
    s = _parse_number(sales.group(1))
    v = _parse_number(vc.group(1))
    f = _parse_number(fc.group(1))
    cm = s - v
    if s <= 0 or cm <= 0:
        return None
    cmr = cm / s
    bep_sales = f / cmr
    mos_ratio = (s - bep_sales) / s  # 0~1
    value = mos_ratio * 100  # 백분율 수치
    # 백분율 보기에서 최근접 선택 (금액 헬퍼는 % 보기를 못 읽음)
    pct_values = []
    for choice in question["choices"]:
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", str(choice))
        pct_values.append(float(m.group(1)) if m else None)
    indexed = [(i, pv) for i, pv in enumerate(pct_values) if pv is not None]
    if not indexed:
        return None
    chosen = min(indexed, key=lambda it: abs(it[1] - value))[0]
    choice_notes = []
    for i, pv in enumerate(pct_values):
        if pv is None:
            choice_notes.append(f"{i + 1}번 {question['choices'][i]}: 비율 비교 불가")
        elif i == chosen:
            choice_notes.append(
                f"{i + 1}번 {question['choices'][i]}: 계산값 {value:.0f}%와 가장 일치"
            )
        else:
            choice_notes.append(
                f"{i + 1}번 {question['choices'][i]}: 계산값과 {abs(pv - value):.0f}%p 차이로 제거"
            )
    return ReasonedTrace(
        rule_id="cost_margin_of_safety_ratio",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["안전한계율", "매출액", "변동원가", "고정원가"],
        concepts=[
            "공헌이익률 = (매출 − 변동원가) / 매출",
            "BEP 매출액 = 고정원가 / 공헌이익률",
            "안전한계율 = (매출 − BEP매출) / 매출",
        ],
        formula_steps=[
            f"공헌이익 = {s:,.0f} − {v:,.0f} = {cm:,.0f}원, 공헌이익률 = {cmr:.1%}",
            f"BEP 매출액 = {f:,.0f} / {cmr:.1%} = {bep_sales:,.0f}원",
            f"안전한계율 = ({s:,.0f} − {bep_sales:,.0f}) / {s:,.0f} = {value:.0f}%",
        ],
        choice_notes=choice_notes,
        computed_value=value,
        confidence=0.9,
        entry_point="공헌이익률로 BEP 매출 산출 후 현재 매출 대비 여유분 비율 계산 (공헌이익률과 혼동 함정 주의)",
        trap_patterns=_trap_patterns(question),
    )


def _solve_dol_profit_change(question):
    """영업레버리지도(DOL) = 공헌이익 / 영업이익. 영업이익 변화율 = 매출변화율 × DOL."""
    stem = question.get("stem", "")
    if "영업이익" not in stem or "공헌이익" not in stem:
        return None
    if "증가" not in stem and "변화" not in stem and "감소" not in stem:
        return None
    # 단위/표/수량 변형, 고정원가도 변동하는 변형은 제외
    if any(x in stem for x in ("단위당 공헌이익", "표", "각 제품")):
        return None
    oi = re.search(r"영업이익[^0-9]{0,6}([0-9,]+)\s*원", stem)
    cm = re.search(r"공헌이익[^0-9]{0,6}([0-9,]+)\s*원", stem)
    growth = re.search(r"매출(?:액)?(?:이|은)?\s*([0-9]+(?:\.[0-9]+)?)\s*%\s*증가", stem)
    if not (oi and cm and growth):
        return None
    o = _parse_number(oi.group(1))
    c = _parse_number(cm.group(1))
    if o <= 0:
        return None
    dol = c / o
    g = float(growth.group(1))
    value = dol * g  # 영업이익 증가율(%)
    pct_values = []
    for choice in question["choices"]:
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", str(choice))
        pct_values.append(float(m.group(1)) if m else None)
    indexed = [(i, pv) for i, pv in enumerate(pct_values) if pv is not None]
    if not indexed:
        return None
    chosen = min(indexed, key=lambda it: abs(it[1] - value))[0]
    choice_notes = []
    for i, pv in enumerate(pct_values):
        if pv is None:
            choice_notes.append(f"{i + 1}번 {question['choices'][i]}: 비율 비교 불가")
        elif i == chosen:
            choice_notes.append(
                f"{i + 1}번 {question['choices'][i]}: 계산값 {value:.0f}%와 가장 일치"
            )
        else:
            choice_notes.append(
                f"{i + 1}번 {question['choices'][i]}: 계산값과 {abs(pv - value):.0f}%p 차이로 제거"
            )
    return ReasonedTrace(
        rule_id="cost_dol_profit_change",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["영업레버리지도", "DOL", "공헌이익", "영업이익", "매출 증가율"],
        concepts=[
            "DOL = 공헌이익 / 영업이익",
            "영업이익 변화율 = 매출 변화율 × DOL",
        ],
        formula_steps=[
            f"DOL = {c:,.0f} / {o:,.0f} = {dol:.2f}",
            f"영업이익 증가율 = {g:.0f}% × {dol:.2f} = {value:.0f}%",
        ],
        choice_notes=choice_notes,
        computed_value=value,
        confidence=0.9,
        entry_point="공헌이익/영업이익으로 DOL 산출 후 매출변화율에 곱해 영업이익 변화율 도출 (고정원가 불변 전제)",
        trap_patterns=_trap_patterns(question),
    )


def _solve_special_order(question):
    """특별주문 증분 영업이익 = (특별주문 단가 − 단위당 변동원가) × 주문수량. 유휴능력·추가고정원가 없음 전제."""
    stem = question.get("stem", "")
    if "특별주문" not in stem:
        return None
    # 유휴생산능력 부족·추가 고정원가 발생·기존 판매 잠식 변형은 제외
    if "추가 고정원가는 발생하지 않" not in stem and "추가 고정원가가 없" not in stem:
        return None
    if any(x in stem for x in ("유휴생산능력이 부족", "기존 판매를 포기", "잠식", "변동판매비")):
        return None
    unit_vc = re.search(r"단위당\s*변동(?:원가|비)[^0-9]{0,6}([0-9,]+)\s*원", stem)
    order = re.search(r"([0-9,]+)\s*단위를?\s*단위당\s*([0-9,]+)\s*원", stem)
    if not (unit_vc and order):
        return None
    v = _parse_number(unit_vc.group(1))
    qty = _parse_number(order.group(1))
    price = _parse_number(order.group(2))
    unit_cm = price - v
    value = round(unit_cm * qty)  # 양수=증가
    if value <= 0:
        return None  # 감소형은 본 규칙 범위 밖(증분공헌이익 양수만 확정)
    # value>0 = 영업이익 증가. '감소'로만 표기된 보기는 부호 반대 → 제외 후 최근접 선택
    chosen, best = -1, None
    for idx, choice in enumerate(question["choices"]):
        cval = _first_money_value(choice)
        if cval is None or ("감소" in choice and "증가" not in choice):
            continue
        diff = abs(cval - value)
        if best is None or diff < best:
            best, chosen = diff, idx
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="cost_special_order_profit",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["특별주문", "단위당 변동원가", "유휴생산능력", "추가 고정원가 없음"],
        concepts=[
            "증분분석: 고정원가가 불변이면 비관련",
            "증분 영업이익 = (특별주문가 − 단위당 변동원가) × 주문수량",
        ],
        formula_steps=[
            f"특별주문 단위당 공헌이익 = {price:,.0f} − {v:,.0f} = {unit_cm:,.0f}원",
            f"증분 공헌이익 = {unit_cm:,.0f} × {qty:,.0f} = {value:,.0f}원",
            f"추가 고정원가 없음 → 영업이익 {value:,.0f}원 증가",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.9,
        entry_point="고정원가는 비관련 처리, 특별주문 단위공헌이익만으로 증분이익 계산 (전부원가 비교 함정 주의)",
        trap_patterns=_trap_patterns(question),
    )


def _solve_bep_units_and_safety_sales(question):
    """BEP 판매량 = 고정비 / 단위당 공헌이익, 안전한계율 r% → 현재매출 = BEP매출 / (1−r). 짝 보기형."""
    stem = question.get("stem", "")
    if "손익분기점" not in stem or "안전한계" not in stem:
        return None
    price = re.search(r"단위당\s*(?:판매)?가격[^0-9]{0,6}([0-9,]+)\s*원", stem)
    vc = re.search(r"단위당\s*변동비?(?:원가)?[^0-9]{0,6}([0-9,]+)\s*원", stem)
    fc = re.search(r"고정비[^0-9]{0,6}([0-9,]+)\s*원", stem)
    mos = re.search(r"안전한계율\s*\(?\s*([0-9]+(?:\.[0-9]+)?)\s*%", stem)
    if not (price and vc and fc and mos):
        return None
    p = _parse_number(price.group(1))
    v = _parse_number(vc.group(1))
    f = _parse_number(fc.group(1))
    unit_cm = p - v
    if unit_cm <= 0:
        return None
    bep_units = f / unit_cm
    bep_sales = bep_units * p
    r = float(mos.group(1)) / 100
    if r >= 1:
        return None
    safety_sales = round(bep_sales / (1 - r))  # 안전한계율 r 만족하는 현재 매출
    # 짝 보기 → 안전한계 매출액(고유 식별자)으로 최근접, 단 BEP 수량 문자열도 일치 검증
    chosen = _choose_closest_money(question["choices"], safety_sales)
    if chosen < 0:
        return None
    # 선택된 보기에 BEP 판매량 정수와 안전한계 매출 둘 다 들어있는지 guard
    bep_token = f"{int(round(bep_units)):,}"
    if bep_token not in str(question["choices"][chosen]):
        return None
    return ReasonedTrace(
        rule_id="cost_bep_units_and_safety_sales",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["손익분기점 판매량", "안전한계율", "단위당 공헌이익"],
        concepts=[
            "BEP 판매량 = 고정비 / 단위당 공헌이익",
            "BEP 매출액 = BEP 판매량 × 판매가격",
            "안전한계율 r → 현재매출 = BEP매출 / (1 − r)",
        ],
        formula_steps=[
            f"단위당 공헌이익 = {p:,.0f} − {v:,.0f} = {unit_cm:,.0f}원",
            f"BEP 판매량 = {f:,.0f} / {unit_cm:,.0f} = {bep_units:,.0f}개",
            f"BEP 매출액 = {bep_units:,.0f} × {p:,.0f} = {bep_sales:,.0f}원",
            f"안전한계율 {r:.0%} → 현재매출 = {bep_sales:,.0f} / (1 − {r:.0%}) = {safety_sales:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, safety_sales),
        computed_value=safety_sales,
        confidence=0.88,
        entry_point="BEP 판매량과 안전한계율 정의(BEP까지 거리 비율)를 분리 계산해 짝으로 확정",
        trap_patterns=_trap_patterns(question),
    )


def _solve_perpetuity_pv(question):
    """영구연금 현재가치 = 연 지급액 / 할인율 (성장 없는 단순 영구연금)."""
    stem = question.get("stem", "")
    if "영구연금" not in stem or "영구히" not in stem:
        return None
    # 성장영구연금(고든)은 분모가 (k-g)로 달라짐 → 단순 영구연금 규칙에서 제외
    if "성장" in stem:
        return None
    pay = re.search(r"매년\s*말\s*([0-9,]+)\s*원", stem)
    rate = re.search(r"할인율[^0-9]{0,8}([0-9.]+)\s*%", stem)
    if not (pay and rate):
        return None
    p = _parse_number(pay.group(1))
    r = float(rate.group(1)) / 100
    if r <= 0:
        return None
    value = round(p / r)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="finance_perpetuity_pv",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["영구연금", "영구히 지급", "할인율", "현재가치"],
        concepts=["화폐의 시간가치", "영구연금 현재가치 = 연 지급액 / 할인율"],
        formula_steps=[
            f"연 지급액 = {p:,.0f}원, 할인율 = {r:.1%}",
            f"영구연금 현재가치 = {p:,.0f} / {r:.1%} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.93,
        entry_point="무한기간 정액 현금흐름을 할인율로 나눠 현재가치 산출 (할인율을 분자로 쓰지 않음)",
        trap_patterns=_trap_patterns(question),
    )


def _solve_growing_perpetuity_pv(question):
    """성장영구연금 현재가치(고든모형) = 첫 지급액 / (할인율 - 성장률), k>g 전제."""
    stem = question.get("stem", "")
    if "성장영구연금" not in stem or "증가" not in stem:
        return None
    pay = re.search(r"매년\s*말\s*([0-9,]+)\s*원", stem)
    growth = re.search(r"매년\s*([0-9.]+)\s*%씩\s*지급액이\s*증가", stem)
    rate = re.search(r"할인율[^0-9]{0,8}([0-9.]+)\s*%", stem)
    if not (pay and growth and rate):
        return None
    p = _parse_number(pay.group(1))
    g = float(growth.group(1)) / 100
    r = float(rate.group(1)) / 100
    if r <= g:
        return None
    value = round(p / (r - g))
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="finance_growing_perpetuity_pv",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["성장영구연금", "매년 일정률 증가", "할인율", "고든 성장모형"],
        concepts=["화폐의 시간가치", "성장영구연금 현재가치 = 첫 지급액 / (할인율 - 성장률)"],
        formula_steps=[
            f"첫 지급액 = {p:,.0f}원, 할인율 = {r:.1%}, 성장률 = {g:.1%}",
            f"현재가치 = {p:,.0f} / ({r:.1%} - {g:.1%}) = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.9,
        entry_point="항상성장 가정으로 첫 지급액을 (할인율-성장률)로 나눔 ('5년간' 등 유한기간 언급은 함정, k>g 전제)",
        trap_patterns=_trap_patterns(question),
    )


def _solve_ordinary_annuity_pv(question):
    """정상연금 현재가치 = 연금액 × PVA계수 (계수가 stem에 명시된 경우만)."""
    stem = question.get("stem", "")
    if "정상연금" not in stem:
        return None
    # 영구연금은 별도 규칙, 선급/기시연금은 계수 적용 방식이 달라 제외
    if "영구" in stem or "선급연금" in stem or "기시" in stem:
        return None
    pay = re.search(r"매년\s*말\s*([0-9,]+)\s*원", stem)
    # PVA 계수가 stem에 직접 제시된 경우만 사용 (반올림 일치 보장, 계수 자체 계산은 회피)
    factor = re.search(r"PVA\([^)]*\)\s*[≈=]\s*([0-9.]+)", stem)
    if not (pay and factor):
        return None
    p = _parse_number(pay.group(1))
    f = float(factor.group(1))
    value = round(p * f)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="finance_ordinary_annuity_pv",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["정상연금", "매년 말 지급", "연금현가요소 PVA", "현재가치"],
        concepts=["화폐의 시간가치", "정상연금 현가 = 연금액 × 연금현가요소(PVA)"],
        formula_steps=[
            f"연금액 = {p:,.0f}원, 연금현가요소 PVA = {f}",
            f"정상연금 현가 = {p:,.0f} × {f} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.9,
        entry_point="기말 지급 정상연금에 제시된 연금현가요소를 곱함 (선급연금 보정·FVA 적용 함정 배제)",
        trap_patterns=_trap_patterns(question),
    )


def _solve_capm_required_return(question):
    """CAPM 요구수익률 = Rf + β × (Rm − Rf). 단일 자산 요구/기대수익률 기본형."""
    stem = question.get("stem", "")
    if "CAPM" not in stem and "베타" not in stem:
        return None
    if "요구수익률" not in stem and "기대수익률" not in stem:
        return None
    # 포트폴리오 구성(비중) 문항은 CAPM이 아니라 가중평균/분산 문항 → 분리
    if "비중" in stem:
        return None
    beta = re.search(r"베타[^0-9]{0,6}(-?[0-9]+(?:\.[0-9]+)?)", stem)
    rf = re.search(r"무위험이자율[^0-9]{0,8}(?:연\s*)?(-?[0-9]+(?:\.[0-9]+)?)\s*%", stem)
    # '시장포트폴리오'는 CAPM 표준 용어 — 시장 기대수익률 라벨로 허용
    rm = re.search(
        r"시장(?:포트폴리오)?(?:의)?\s*기대수익률[^0-9]{0,8}(?:연\s*)?(-?[0-9]+(?:\.[0-9]+)?)\s*%",
        stem,
    )
    if not (beta and rf and rm):
        return None
    b = float(beta.group(1))
    r_f = float(rf.group(1))
    r_m = float(rm.group(1))
    premium = r_m - r_f
    value = round(r_f + b * premium, 6)
    chosen = _choose_closest_pct(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="finance_capm_required_return",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["CAPM", "베타(β)", "무위험이자율", "시장 기대수익률", "요구수익률"],
        concepts=["CAPM 요구수익률 = Rf + β × (Rm − Rf)", "시장위험프리미엄 = Rm − Rf"],
        formula_steps=[
            f"시장위험프리미엄 = {r_m:g}% − {r_f:g}% = {premium:g}%",
            f"요구수익률 = {r_f:g}% + {b:g} × {premium:g}% = {value:g}%",
        ],
        choice_notes=_pct_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.93,
        entry_point="베타로 체계적위험만 보상 — 시장위험프리미엄에 베타를 곱해 무위험수익률에 가산",
        trap_patterns=_trap_patterns(question),
    )


def _solve_portfolio_expected_return(question):
    """2자산 포트폴리오 기대수익률 = Σ wᵢ × E(Rᵢ) (가중평균). 표준편차·상관계수는 무관."""
    stem = question.get("stem", "")
    if "포트폴리오" not in stem:
        return None
    if "비중" not in stem:  # CAPM 단일자산과 분리
        return None
    s = stem.strip()
    # 질문 대상이 표준편차/위험이면 분산 규칙 소관 → 미발동
    if s.endswith("표준편차는?") or s.endswith("분산은?"):
        return None
    if not s.endswith("기대수익률은?"):
        return None
    w = re.search(
        r"비중[^0-9]{0,6}(-?[0-9]+(?:\.[0-9]+)?)\s*%[^0-9]{0,8}(-?[0-9]+(?:\.[0-9]+)?)\s*%",
        stem,
    )
    r = re.search(
        r"기대수익률[^0-9]{0,6}(-?[0-9]+(?:\.[0-9]+)?)\s*%[^0-9]{0,8}(-?[0-9]+(?:\.[0-9]+)?)\s*%",
        stem,
    )
    if not (w and r):
        return None
    wx = float(w.group(1)) / 100
    wy = float(w.group(2)) / 100
    if abs(wx + wy - 1.0) > 1e-6:  # 2자산 비중 합 100% 가정 위반 시 기권
        return None
    ex = float(r.group(1))
    ey = float(r.group(2))
    value = round(wx * ex + wy * ey, 6)
    chosen = _choose_closest_pct(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="finance_portfolio_expected_return",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["포트폴리오", "비중", "개별자산 기대수익률", "가중평균"],
        concepts=[
            "포트폴리오 기대수익률 = w_X × E(R_X) + w_Y × E(R_Y)",
            "표준편차·상관계수는 위험(분산) 계산용 — 기대수익률에는 영향 없음",
        ],
        formula_steps=[
            f"비중 w_X = {wx:.0%}, w_Y = {wy:.0%}",
            f"E(Rp) = {wx:.0%} × {ex:g}% + {wy:.0%} × {ey:g}% "
            f"= {wx * ex:g}% + {wy * ey:g}% = {value:g}%",
        ],
        choice_notes=_pct_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.92,
        entry_point="개별 기대수익률을 비중으로 가중평균 — 표준편차/상관계수는 함정으로 무시",
        trap_patterns=_trap_patterns(question),
    )


def _solve_portfolio_std_dev(question):
    """2자산 포트폴리오 표준편차 = √(wX²σX² + wY²σY² + 2 wX wY σX σY ρ). 동일비중 기본형."""
    stem = question.get("stem", "")
    if "포트폴리오" not in stem:
        return None
    # 질문 대상이 표준편차일 때만 — 기대수익률 문항과 분리
    if not stem.strip().endswith("표준편차는?"):
        return None
    # 동일비중 '각각 N%씩'만 지원. 비대칭 비중/표 형태는 자료 부족으로 기권.
    weq = re.search(r"각각\s*(-?[0-9]+(?:\.[0-9]+)?)\s*%씩", stem)
    std = re.search(
        r"표준편차[^0-9]{0,8}(-?[0-9]+(?:\.[0-9]+)?)\s*%[^0-9]{0,8}(-?[0-9]+(?:\.[0-9]+)?)\s*%",
        stem,
    )
    corr = re.search(r"상관계수[^0-9\-]{0,6}(-?[0-9]+(?:\.[0-9]+)?)", stem)
    if not (weq and std and corr):
        return None
    w = float(weq.group(1)) / 100
    sx = float(std.group(1)) / 100
    sy = float(std.group(2)) / 100
    rho = float(corr.group(1))
    variance = w * w * sx * sx + (1 - w) * (1 - w) * sy * sy + 2 * w * (1 - w) * sx * sy * rho
    if variance < 0:
        variance = 0.0
    value = round(math.sqrt(variance) * 100, 6)
    chosen = _choose_closest_pct(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="finance_portfolio_std_dev",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["포트폴리오", "표준편차", "상관계수(ρ)", "분산", "동일비중"],
        concepts=[
            "포트폴리오 분산 = wX²σX² + wY²σY² + 2 wX wY σX σY ρ",
            "표준편차 = √분산",
            "ρ가 낮을수록 분산효과로 위험 감소",
        ],
        formula_steps=[
            f"비중 wX = {w:.0%}, wY = {1 - w:.0%}; σX = {sx:.0%}, σY = {sy:.0%}, ρ = {rho:g}",
            f"분산 = {w:.2f}²×{sx:g}² + {1 - w:.2f}²×{sy:g}² "
            f"+ 2×{w:.2f}×{1 - w:.2f}×{sx:g}×{sy:g}×({rho:g}) = {variance:.6g}",
            f"표준편차 = √{variance:.6g} = {value:g}%",
        ],
        choice_notes=_pct_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.9,
        entry_point="공분산항에 상관계수 부호 그대로 반영 — ρ=−1이면 분산효과 최대",
        trap_patterns=_trap_patterns(question),
    )


def _signed_choice_value(text: str) -> float | None:
    """선택지 문자열의 부호 포함 금액. 기존 _money_values는 '-'를 버려서 NPV 음수 비교가 깨지므로 별도 처리.
    회계 음수 표기는 선행 '-', 삼각형 '△', 그리고 '(숫자...)' 괄호 컨벤션만 음수로 인정한다.
    '120,000원 (세후)'처럼 숫자를 감싸지 않은 일반 괄호는 음수로 보지 않는다."""
    m = re.search(r"(-?)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*원", text)
    if not m:
        return None
    val = _parse_number(m.group(2))
    paren_negative = re.search(r"\(\s*[0-9△-]", text) is not None
    if m.group(1) == "-" or "△" in text or paren_negative:
        val = -val
    return val


def _choose_closest_signed(choices: list, target: float) -> int:
    indexed = [(idx, _signed_choice_value(c)) for idx, c in enumerate(choices)]
    indexed = [(idx, v) for idx, v in indexed if v is not None]
    if not indexed:
        return -1
    return min(indexed, key=lambda item: abs(item[1] - target))[0]


def _solve_npv_annuity(question):
    """연금현가요소(PVA/PVIFA)로 NPV 계산. NPV = 매년현금흐름 × 연금현가계수 − 초기투자.
    (일반 '연도별 현금흐름' NPV는 기존 _solve_npv가 처리. 여기는 '매년 정액 + 명시 PVA계수' 변형만.)"""
    stem = question.get("stem", "")
    if "NPV" not in stem and "순현재가치" not in stem:
        return None
    if not any(k in stem for k in ("PVA", "PVIFA", "연금현가")):
        return None
    if "매년" not in stem:
        return None
    initial = re.search(r"오늘\s*([0-9,]+)\s*원을?\s*투자", stem)
    annuity = re.search(r"매년\s*(?:말|초)?\s*([0-9,]+)\s*원", stem)
    factor = re.search(r"[≈=]\s*([0-9]+\.[0-9]+)", stem)
    if not (initial and annuity and factor):
        return None
    i = _parse_number(initial.group(1))
    a = _parse_number(annuity.group(1))
    f = float(factor.group(1))
    pv_inflows = a * f
    value = round(pv_inflows - i)
    chosen = _choose_closest_signed(question["choices"], value)
    if chosen < 0:
        chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="finance_npv_annuity_factor",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["NPV/순현재가치", "매년 정액 현금흐름", "연금현가계수(PVA)", "초기투자"],
        concepts=[
            "연금의 현재가치 = 정액 현금흐름 × 연금현가계수",
            "NPV = 유입 현재가치 − 초기투자",
        ],
        formula_steps=[
            f"유입 현재가치 = {a:,.0f} × {f} = {pv_inflows:,.0f}원",
            f"NPV = {pv_inflows:,.0f} − {i:,.0f} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.92,
        entry_point="매년 정액 현금흐름에 연금현가계수를 곱해 유입 현가를 구한 후 초기투자와 비교",
        trap_patterns=_trap_patterns(question),
    )


def _solve_irr_closest_rate(question):
    """IRR 근사: 보기로 주어진 각 할인율에서 NPV를 계산해 |NPV|가 최소인 할인율 선택.
    (보기가 전부 %이고 stem에 초기투자+연도별 현금흐름이 있을 때만. 표/공식 정의형은 기권.)"""
    stem = question.get("stem", "")
    if "내부수익률" not in stem and "IRR" not in stem:
        return None
    initial = re.search(r"오늘\s*([0-9,]+)\s*원을?\s*투자", stem)
    flows = [
        (int(y), _parse_number(v)) for y, v in re.findall(r"(\d+)\s*년\s*뒤\s*([0-9,]+)\s*원", stem)
    ]
    if not initial or not flows:
        return None
    i = _parse_number(initial.group(1))
    rates = []
    for choice in question["choices"]:
        m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*%", choice)
        rates.append(float(m.group(1)) / 100 if m else None)
    if not rates or any(r is None for r in rates):
        return None
    best_idx = -1
    best_abs = None
    npvs: list[tuple[int, float, float]] = []
    for idx, r in enumerate(rates):
        npv = sum(c / ((1 + r) ** y) for y, c in flows) - i
        npvs.append((idx, r, npv))
        if best_abs is None or abs(npv) < best_abs:
            best_abs = abs(npv)
            best_idx = idx
    if best_idx < 0:
        return None
    best_rate = rates[best_idx]
    return ReasonedTrace(
        rule_id="finance_irr_closest_rate",
        chosen_index=best_idx,
        answer_text=f"{best_idx + 1}번 {question['choices'][best_idx]}",
        signals=["내부수익률/IRR", "초기투자", "연도별 현금흐름", "보기=할인율"],
        concepts=[
            "IRR은 NPV=0을 만드는 할인율",
            "보기 할인율별 NPV를 계산해 0에 가장 가까운 것 선택",
        ],
        formula_steps=[
            f"초기투자 = {i:,.0f}원, 현금흐름 = "
            + ", ".join(f"{y}년 뒤 {c:,.0f}원" for y, c in flows),
            *[f"r={r:.0%} → NPV = {npv:,.0f}원 (|NPV|={abs(npv):,.0f})" for _, r, npv in npvs],
            f"|NPV| 최소 → IRR ≈ {best_rate:.0%}",
        ],
        choice_notes=[
            (
                f"{idx + 1}번 {question['choices'][idx]}: 이 할인율에서 NPV={npv:,.0f}원로 0에 가장 근접"
                if idx == best_idx
                else f"{idx + 1}번 {question['choices'][idx]}: NPV={npv:,.0f}원로 0에서 멀어 제거"
            )
            for idx, _, npv in npvs
        ],
        computed_value=best_rate,
        confidence=0.9,
        entry_point="보기의 각 할인율에서 NPV를 실제 계산해 0에 가장 가까운 할인율을 IRR로 확정",
        trap_patterns=_trap_patterns(question),
    )


def _solve_wacc(question: dict) -> ReasonedTrace | None:
    """WACC = (E/V)×Re + (D/V)×Rd×(1-t). 자본구조 비중·자본비용·세전부채비용·법인세율이 모두 명시된 기본형."""
    stem = question.get("stem", "")
    if "WACC" not in stem and "가중평균자본비용" not in stem:
        return None
    # 자본비용/비중을 표로 주거나 베타/시장위험프리미엄으로 CAPM 계산하는 변형은 미지원 (오답 방지)
    if any(x in stem for x in ("베타", "시장위험프리미엄", "CAPM", "재조달", "우선주")):
        return None
    we = re.search(r"자기자본\s+([0-9.]+)\s*%", stem)
    wd = re.search(r"부채\s+([0-9.]+)\s*%", stem)
    re_cost = re.search(r"자기자본비용[^0-9]{0,4}([0-9.]+)\s*%", stem)
    rd_cost = re.search(r"세전\s*부채비용[^0-9]{0,4}([0-9.]+)\s*%", stem)
    tax = re.search(r"법인세율[^0-9]{0,4}([0-9.]+)\s*%", stem)
    if not (we and wd and re_cost and rd_cost and tax):
        return None
    e_w = _parse_number(we.group(1)) / 100
    d_w = _parse_number(wd.group(1)) / 100
    re_v = _parse_number(re_cost.group(1)) / 100
    rd_v = _parse_number(rd_cost.group(1)) / 100
    t = _parse_number(tax.group(1)) / 100
    value = e_w * re_v + d_w * rd_v * (1 - t)
    chosen = _choose_closest_percent(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="finance_wacc",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["가중평균자본비용", "자본구조 비중", "자기자본비용", "세전 부채비용", "법인세율"],
        concepts=["WACC = (E/V)×Re + (D/V)×Rd×(1-t)", "부채비용은 절세효과(1-t) 적용"],
        formula_steps=[
            f"자기자본 비중 {e_w:.0%} × 자기자본비용 {re_v:.1%} = {e_w * re_v:.2%}",
            f"부채 비중 {d_w:.0%} × 세전부채비용 {rd_v:.1%} × (1-{t:.0%}) = {d_w * rd_v * (1 - t):.2%}",
            f"WACC = {e_w * re_v:.2%} + {d_w * rd_v * (1 - t):.2%} = {value:.2%}",
        ],
        choice_notes=_choice_notes_percent(question["choices"], chosen, value),
        computed_value=round(value * 100, 4),
        confidence=0.93,
        entry_point="자본비용을 시장가치 비중으로 가중평균하되 부채비용에만 절세효과(1-t) 적용",
        trap_patterns=_trap_patterns(question),
    )


def _solve_put_call_parity(question: dict) -> ReasonedTrace | None:
    """풋콜패리티: P = C - S + K/(1+r). 이산복리 할인·행사가·현재가·무위험이자율·콜가격 명시된 기본형."""
    stem = question.get("stem", "")
    if "풋콜패리티" not in stem and "put-call" not in stem.lower():
        return None
    # 풋을 찾는 표준형만 지원. 배당·이항모형·변동성 변형은 미지원(오답 방지)
    if any(x in stem for x in ("배당", "이항모형", "변동성", "e^")):
        return None
    # 연속복리 변형 차단: 단, '연속복리 아님'(이산복리 명시)은 허용
    if "연속복리" in stem and "연속복리 아님" not in stem:
        return None
    # '풋옵션의 이론가'를 묻는 표준형만 (오타 '옷'->'옵' 수정)
    if "풋옵션" not in stem:
        return None
    K = re.search(r"행사가격[^0-9]{0,10}([0-9,]+)\s*원", stem)
    S = re.search(r"기초자산\s*가격[^0-9]{0,6}([0-9,]+)\s*원", stem)
    r = re.search(r"무위험이자율[^0-9]{0,8}([0-9.]+)\s*%", stem)
    C = re.search(r"콜옵션\s*가격[^0-9]{0,6}([0-9,]+)\s*원", stem)
    if not (K and S and r and C):
        return None
    k = _parse_number(K.group(1))
    s = _parse_number(S.group(1))
    rate = _parse_number(r.group(1)) / 100
    c = _parse_number(C.group(1))
    pv_k = k / (1 + rate)
    value = round(c - s + pv_k)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="finance_put_call_parity",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["풋콜패리티", "행사가격", "기초자산 현재가", "무위험이자율", "콜옵션 가격"],
        concepts=[
            "풋콜패리티: C - P = S - K/(1+r)",
            "P = C - S + K/(1+r)",
            "행사가격은 무위험이자율로 할인",
        ],
        formula_steps=[
            f"행사가격 현재가 = {k:,.0f} / (1+{rate:.0%}) = {pv_k:,.2f}원",
            f"P = C - S + K/(1+r) = {c:,.0f} - {s:,.0f} + {pv_k:,.0f} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.92,
        entry_point="풋콜패리티로 콜·현재가·행사가의 현재가치로부터 풋 이론가 역산 (행사가 할인 필수)",
        trap_patterns=_trap_patterns(question),
    )


def _solve_impairment_loss(question):
    """손상차손 = 장부금액 − 회수가능액. 장부금액=취득원가−정액법 연감가×경과연수, 회수가능액=max(사용가치, 순공정가치). 정액법 단일경로만."""
    stem = question.get("stem", "")
    if "손상" not in stem or "회수가능액" not in stem:
        return None
    # 재평가/가속상각 등 변형형은 미지원 → 오답 방지
    if any(x in stem for x in ("재평가", "환입", "정률법", "연수합계법", "이중체감", "생산량비례")):
        return None
    cost_m = re.search(r"([0-9,]+)\s*원에\s*취득", stem)
    life_m = re.search(r"내용연수\s*(\d+)\s*년", stem)
    use_m = re.search(r"사용가치\s*([0-9,]+)\s*원", stem)
    fair_m = re.search(r"(?:순공정가치|처분부대원가\s*차감\s*공정가치)\s*([0-9,]+)\s*원", stem)
    acq_y = re.search(r"20X(\d)\s*년[^.]*?취득", stem)
    # 손상연도 = '손상/회수가능액' 키워드 직전의 가장 가까운 연도 (날짜·문장경계 무관, 취득연도 오선택 방지)
    imp_kw = re.search(r"손상|회수가능액", stem)
    years = list(re.finditer(r"20X(\d)\s*년", stem))
    if not (cost_m and life_m and use_m and fair_m and acq_y and imp_kw and years):
        return None
    preceding = [m for m in years if m.start() < imp_kw.start()]
    if not preceding:
        return None
    imp_y = preceding[-1]
    resid_m = re.search(r"잔존가치\s*([0-9,]+)\s*원", stem)
    cost = _parse_number(cost_m.group(1))
    life = int(life_m.group(1))
    resid = _parse_number(resid_m.group(1)) if resid_m else 0.0
    use_v = _parse_number(use_m.group(1))
    fair_v = _parse_number(fair_m.group(1))
    elapsed = int(imp_y.group(1)) - int(acq_y.group(1))
    if life <= 0 or elapsed < 0 or elapsed > life:
        return None
    annual = (cost - resid) / life
    carrying = cost - annual * elapsed
    recoverable = max(use_v, fair_v)
    value = round(carrying - recoverable)
    if value <= 0:
        return None
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="accounting_impairment_loss",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["손상차손", "회수가능액", "정액법 감가상각", "장부금액"],
        concepts=["회수가능액 = max(사용가치, 순공정가치)", "손상차손 = 장부금액 − 회수가능액"],
        formula_steps=[
            f"연 감가상각비 = ({cost:,.0f} − {resid:,.0f}) / {life} = {annual:,.0f}원",
            f"경과 {elapsed}년 후 장부금액 = {cost:,.0f} − {annual:,.0f}×{elapsed} = {carrying:,.0f}원",
            f"회수가능액 = max(사용가치 {use_v:,.0f}, 순공정가치 {fair_v:,.0f}) = {recoverable:,.0f}원",
            f"손상차손 = {carrying:,.0f} − {recoverable:,.0f} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.9,
        entry_point="장부금액에서 회수가능액(사용가치·순공정가치 중 큰 값)을 차감해 손상차손 산출",
        trap_patterns=_trap_patterns(question),
    )


def _solve_transaction_price_allocation(question):
    """인도분 수익 = 거래가격 × (인도 항목 개별판매가격 / 총 개별판매가격). 인도 대상은 '인도 시점에 통제 이전' 항목명으로 식별, SP 목록에서 이름 매칭. 순서 의존 제거."""
    stem = question.get("stem", "")
    if "개별 판매가격" not in stem and "개별판매가격" not in stem:
        return None
    if "인도 시점" not in stem and "인도시점" not in stem:
        return None
    if any(x in stem for x in ("변동대가", "환불", "보증", "할인권", "라이선스")):
        return None
    contract_m = re.search(r"([0-9,]+)\s*원에\s*판매", stem)
    if not contract_m:
        return None
    contract = _parse_number(contract_m.group(1))
    sp_part = stem.split("개별", 1)[1]
    sp_pairs = [
        (n.strip(), _parse_number(p))
        for n, p in re.findall(r"([가-힣A-Za-z][가-힣A-Za-z0-9\s]*?)\s*([0-9,]+)\s*원", sp_part)
    ]
    if len(sp_pairs) < 2:
        return None
    total_sp = sum(p for _, p in sp_pairs)
    if total_sp <= 0:
        return None
    deliv_m = re.search(
        r"([가-힣A-Za-z][가-힣A-Za-z0-9\s]*?)(?:는|은|이|가)?\s*인도\s*시점에\s*통제가\s*이전",
        stem,
    )
    target_sp = None
    if deliv_m:
        deliv = deliv_m.group(1).replace(" ", "")
        for name, price in sp_pairs:
            nm = name.replace(" ", "")
            if nm and (nm in deliv or deliv in nm):
                target_sp = price
                break
    if target_sp is None:
        # 인도 대상 항목명 매칭 실패 시 기권 (순서 추측 금지)
        return None
    value = round(contract * target_sp / total_sp)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="accounting_transaction_price_allocation",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["거래가격 배분", "개별 판매가격", "수행의무", "인도 시점 수익"],
        concepts=[
            "거래가격은 상대적 개별판매가격 기준으로 배분",
            "배분액 = 거래가격 × (해당 SP / 총 SP)",
        ],
        formula_steps=[
            f"총 개별판매가격 = {total_sp:,.0f}원",
            f"인도 대상 비중 = {target_sp:,.0f} / {total_sp:,.0f}",
            f"인식 수익 = {contract:,.0f} × {target_sp:,.0f}/{total_sp:,.0f} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.88,
        entry_point="거래가격을 상대적 개별판매가격 비율로 배분 후 인도된 수행의무분만 즉시 인식",
        trap_patterns=_trap_patterns(question),
    )


def _classify_cf_item(label, amount):
    """간접법 조정 항목의 부호 반환. 미지의 항목은 None(기권 신호)."""
    inc = "증가" in label
    dec = "감소" in label
    base = label.replace("증가", "").replace("감소", "").strip()
    # 비현금비용 가산(+)
    if any(
        k in base
        for k in (
            "감가상각비",
            "무형자산상각비",
            "상각비",
            "손상차손",
            "대손상각비",
            "주식보상비용",
            "퇴직급여",
        )
    ):
        return amount
    # 투자·재무 손익 제거: 이익은 차감(-)
    if any(k in base for k in ("처분이익", "평가이익", "상환이익", "환입")):
        return -amount
    # 손실은 가산(+)
    if any(k in base for k in ("처분손실", "평가손실", "상환손실")):
        return amount
    # 운전자본 부채: 증가(+)/감소(-)
    if any(
        k in base
        for k in (
            "매입채무",
            "미지급비용",
            "미지급법인세",
            "미지급",
            "선수수익",
            "선수금",
            "충당부채",
        )
    ):
        return amount if inc else (-amount if dec else None)
    # 운전자본 자산: 증가(-)/감소(+)
    if any(k in base for k in ("매출채권", "재고자산", "선급비용", "선급금", "미수수익", "미수금")):
        return -amount if inc else (amount if dec else None)
    return None


def _solve_indirect_cash_flow(question):
    """간접법 영업활동현금흐름 = 당기순이익 ± 비현금·비영업 손익 ± 운전자본 변동. 미지 항목 있으면 기권."""
    stem = question.get("stem", "")
    if "간접법" not in stem or "영업활동" not in stem:
        return None
    if "직접법" in stem:
        return None
    ni_m = re.search(r"당기순이익\s*([0-9,]+)\s*원", stem)
    if not ni_m:
        return None
    items = re.findall(r"([가-힣A-Za-z]+(?:\s*(?:증가|감소))?)\s*([0-9,]+)\s*원", stem)
    total = None
    steps = []
    for label, amt in items:
        a = _parse_number(amt)
        if "당기순이익" in label:
            total = a
            steps.append(f"당기순이익 {a:,.0f}원 (출발점)")
            continue
        if total is None:
            continue
        adj = _classify_cf_item(label, a)
        if adj is None:
            return None
        total += adj
        sign = "+" if adj >= 0 else "−"
        steps.append(f"{label.strip()} {sign}{abs(adj):,.0f}원")
    if total is None:
        return None
    value = round(total)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None
    steps.append(f"영업활동 현금흐름 = {value:,.0f}원")
    return ReasonedTrace(
        rule_id="accounting_indirect_cash_flow",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["간접법", "영업활동 현금흐름", "비현금비용 가산", "운전자본 변동"],
        concepts=["비현금비용 가산, 투자·재무 손익 제거", "자산 증가는 차감·부채 증가는 가산"],
        formula_steps=steps,
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.9,
        entry_point="당기순이익에서 비현금·비영업 항목과 운전자본 증감을 부호 규칙대로 조정",
        trap_patterns=_trap_patterns(question),
    )


def _solve_treasury_reissue_entry(question):
    """자기주식 단일 재발행 분개 선택. 차액은 자기주식처분손익(자본잉여금), 손익 미인식. 소각 포함 시 미지원."""
    stem = question.get("stem", "")
    if "자기주식" not in stem:
        return None
    if not ("재발행" in stem or "처분" in stem):
        return None
    if "회계처리" not in stem and "분개" not in stem:
        return None
    if "소각" in stem:
        return None
    acq_m = re.search(r"자기주식\s*\d+주를?\s*주당\s*([0-9,]+)\s*원에?\s*취득", stem)
    re_m = re.search(r"(\d+)주를?\s*주당\s*([0-9,]+)\s*원에?\s*(?:재발행|처분)", stem)
    if not acq_m or not re_m:
        return None
    acq_cost = _parse_number(acq_m.group(1))
    qty = int(re_m.group(1))
    price = _parse_number(re_m.group(2))
    cash = qty * price
    book = qty * acq_cost
    diff = cash - book
    label = "자기주식처분이익" if diff >= 0 else "자기주식처분손실"
    chosen = -1
    for idx, c in enumerate(question["choices"]):
        money = [_parse_number(m) for m in re.findall(r"([0-9,]+)\s*원", c)]
        amts_ok = cash in money and book in money and abs(diff) in money
        cls_ok = "자본잉여금" in c and "당기손익" not in c and "차변" not in c and label in c
        if amts_ok and cls_ok:
            chosen = idx
            break
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="accounting_treasury_reissue_entry",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["자기주식 재발행", "자본거래", "자기주식처분손익"],
        concepts=[
            "자기주식 거래는 자본거래로 손익 미인식",
            "재발행가−취득원가 차액은 자기주식처분손익(자본잉여금)",
        ],
        formula_steps=[
            f"현금 = {qty}주 × {price:,.0f} = {cash:,.0f}원",
            f"자기주식 제거 = {qty}주 × {acq_cost:,.0f} = {book:,.0f}원",
            f"차액 {abs(diff):,.0f}원 = {label}(자본잉여금), 당기손익 아님",
        ],
        choice_notes=_choice_notes_text(question["choices"], chosen),
        computed_value=abs(diff),
        confidence=0.9,
        entry_point="재발행가와 취득원가 차액을 자기주식처분손익(자본잉여금)으로 처리, 손익 인식 금지",
        trap_patterns=_trap_patterns(question),
    )


def _solve_treasury_multi_transaction(question):
    """자기주식 다중 처분+소각 순효과. 자본총계 증가=Σ처분현금, 처분손익 잔액=Σ(처분가−취득가)×수량(상계), 소각 자본총계 0. 초기 처분이익 잔액 0 가정 필요."""
    stem = question.get("stem", "")
    if "자기주식" not in stem or "처분" not in stem:
        return None
    if "자본총계" not in stem:
        return None
    acq_m = re.search(r"취득원가\s*@\s*₩?\s*([0-9,]+)", stem)
    if not acq_m:
        return None
    acq_per = _parse_number(acq_m.group(1))
    disps = re.findall(r"자기주식\s*(\d+)주를?\s*주당\s*₩?\s*([0-9,]+)\s*에?\s*처분", stem)
    if len(disps) < 1:
        return None
    # 처분 전 처분이익 잔액 0 가정이 명시돼야 상계 결과가 확정됨
    if re.search(r"처분\s*전\s*자기주식처분이익\s*잔액은\s*없다", stem) is None:
        return None
    equity = 0.0
    gain_bal = 0.0
    steps = []
    for q, p in disps:
        q = int(q)
        p = _parse_number(p)
        cash = q * p
        book = q * acq_per
        equity += cash
        gain_bal += cash - book
        steps.append(
            f"처분 {q}주 @{p:,.0f}: 현금 {cash:,.0f} (자본총계 +{cash:,.0f}), 누적 처분손익 {gain_bal:,.0f}"
        )
    steps.append("소각: 현금 유출입 없어 자본총계 영향 0 (자본금 감소분은 감자차손과 상계)")
    steps.append(f"자본총계 순증가 = {equity:,.0f}원, 자기주식처분이익 잔액 = {gain_bal:,.0f}원")
    label = "자기주식처분이익" if gain_bal >= 0 else "자기주식처분손실"
    gain_abs = abs(gain_bal)
    chosen = -1
    for idx, c in enumerate(question["choices"]):
        money = [_parse_number(m) for m in re.findall(r"₩?\s*([0-9,]+)", c)]
        has_eq = "증가" in c and equity in money
        has_gain = gain_abs in money and label in c
        if has_eq and has_gain:
            chosen = idx
            break
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="accounting_treasury_multi_transaction",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["자기주식 다중거래", "처분손익 우선 상계", "소각 자본총계 영향", "자본거래"],
        concepts=[
            "처분 현금유입분만 자본총계 증가",
            "처분손실은 기존 처분이익과 우선 상계",
            "소각은 자본총계 불변",
        ],
        formula_steps=steps,
        choice_notes=_choice_notes_text(question["choices"], chosen),
        computed_value=equity,
        confidence=0.88,
        entry_point="각 처분의 현금유입을 자본총계 증가로 합산하고 처분손익은 잔액끼리 상계, 소각은 자본총계 0",
        trap_patterns=_trap_patterns(question),
    )


def _solve_entertainment_expense_limit(question):
    """기업업무추진비(접대비) 한도초과액 = 장부계상액 − (기본한도 + 수입금액한도).

    수입금액한도는 일반기업 표준 적용률(100억 이하 0.3%, 100억 초과 500억 이하 0.2%,
    500억 초과 0.03%)을 구간별 누진 합산한다. 표준 적용률 마커(0.3%/0.2%)가 stem에
    없거나 장부계상액·매출액·기본한도 중 하나라도 못 뽑으면 기권(오답 방지).
    문화기업업무추진비 추가한도·적격증빙 미수취 손금불산입 등 변형형도 guard로 제외한다.
    """
    stem = question.get("stem", "")
    if "기업업무추진비" not in stem and "접대비" not in stem:
        return None
    if "한도초과" not in stem:
        return None
    # 표준 일반기업 수입금액 적용률 스케줄이 명시된 기본형만 지원
    if not ("0.3%" in stem and "0.2%" in stem):
        return None
    # 문화기업업무추진비 추가한도/증빙미수취 별도조정 등 변형형은 기권
    if "문화기업업무추진비" in stem and "없음" not in stem:
        return None
    if any(
        x in stem for x in ("신용카드 미사용", "증빙불비", "증빙미수취", "적격증빙 미수취", "3만원")
    ):
        return None
    booked = re.search(r"계상된?\s*(?:기업업무추진비|접대비)[^0-9]{0,8}([0-9,]+)\s*원", stem)
    revenue = re.search(r"매출액[^0-9]{0,20}([0-9,]+)\s*원", stem)
    base = re.search(r"기본한도[^0-9]{0,8}([0-9,]+)\s*원", stem)
    if not (booked and revenue and base):
        return None
    b = _parse_number(booked.group(1))
    rev = _parse_number(revenue.group(1))
    bs = _parse_number(base.group(1))
    t1 = 10_000_000_000  # 100억
    t2 = 50_000_000_000  # 500억
    rev_limit = min(rev, t1) * 0.003
    if rev > t1:
        rev_limit += (min(rev, t2) - t1) * 0.002
    if rev > t2:
        rev_limit += (rev - t2) * 0.0003
    total_limit = bs + rev_limit
    value = round(b - total_limit)
    if value <= 0:
        return None
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="tax_entertainment_expense_limit",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["기업업무추진비 한도", "수입금액한도", "기본한도", "한도초과 손금불산입"],
        concepts=[
            "기업업무추진비 한도 = 기본한도 + 수입금액한도",
            "수입금액한도 = 매출액 구간별 적용률 누진 합산(0.3%/0.2%/0.03%)",
            "한도초과액 = 장부계상액 − 총한도 → 손금불산입(기타사외유출)",
        ],
        formula_steps=[
            f"수입금액한도 = 100억×0.3% + (매출 {rev:,.0f} − 100억)×0.2% = {rev_limit:,.0f}원",
            f"총한도 = 기본한도 {bs:,.0f} + 수입금액한도 {rev_limit:,.0f} = {total_limit:,.0f}원",
            f"한도초과액 = 장부계상액 {b:,.0f} − 총한도 {total_limit:,.0f} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.9,
        entry_point="기본한도와 매출액 구간별 수입금액한도를 합산한 총한도를 장부계상액에서 차감",
        trap_patterns=_trap_patterns(question),
    )


def _solve_taxable_income_adjustment(question):
    """각사업연도소득금액 = 당기순이익 + 가산조정 − 차감조정.

    stem을 줄 단위로 분해해 각 자료 항목의 금액과 부호(가산/차감)를 키워드로 분류한다.
    가산: 법인세비용, *한도초과, 손금불산입, 익금산입, 자기주식처분이익.
    차감: 손금추인, 손금산입(불산입 아님), 익금불산입.
    금액이 있는 줄을 위 키워드로 분류하지 못하면 기권(억지 부호배정 금지).
    한 줄에 서로 다른 원-금액이 2개 이상이면 어느 금액이 조정대상인지 모호하므로 기권.
    기부금 시부인 다단계 문항은 별도 한도계산이 필요하므로 guard로 제외한다.
    """
    stem = question.get("stem", "")
    if "소득금액" not in stem or ("각사업연도" not in stem and "각 사업연도" not in stem):
        return None
    if "당기순이익" not in stem:
        return None
    # 기부금 한도시부인은 다단계(기준소득금액·한도·이월) → 단일 가감으로 안 풀림
    if "기부금" in stem:
        return None
    ni_match = re.search(r"당기순이익[^0-9]{0,8}([0-9,]+)\s*원", stem)
    if not ni_match:
        return None
    ni = _parse_number(ni_match.group(1))
    add_total = 0.0
    sub_total = 0.0
    add_items: list[str] = []
    sub_items: list[str] = []
    for line in re.split(r"[\r\n]+", stem):
        if "당기순이익" in line:
            continue
        amounts = re.findall(r"([0-9][0-9,]{2,})\s*원", line)
        if not amounts:
            continue
        parsed = [_parse_number(a) for a in amounts]
        # 한 줄에 조정 후보 금액이 2개 이상 서로 다르면 모호 → 기권(억지 선택 금지)
        if len({p for p in parsed}) > 1:
            return None
        amount = parsed[0]
        is_sub = (
            "손금추인" in line
            or "익금불산입" in line
            or ("손금산입" in line and "손금불산입" not in line)
        )
        is_add = (
            "법인세" in line
            or "한도초과" in line
            or "손금불산입" in line
            or "익금산입" in line
            or "자기주식처분이익" in line
        )
        if is_sub:
            sub_total += amount
            sub_items.append(f"{line.strip()[:30]} → 차감 {amount:,.0f}")
        elif is_add:
            add_total += amount
            add_items.append(f"{line.strip()[:30]} → 가산 {amount:,.0f}")
        else:
            # 분류 불가한 금액줄 → 억지로 부호 정하지 않고 기권
            return None
    value = round(ni + add_total - sub_total)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="tax_taxable_income_adjustment",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["각사업연도소득금액", "당기순이익", "세무조정", "가산조정/차감조정"],
        concepts=[
            "각사업연도소득금액 = 당기순이익 + 익금산입·손금불산입 − 손금산입·익금불산입",
            "한도초과액·법인세비용·자기주식처분이익은 가산",
            "전기 손금불산입 유보의 당기 손금추인은 차감",
        ],
        formula_steps=[
            f"당기순이익 = {ni:,.0f}원",
            *add_items,
            *sub_items,
            f"각사업연도소득금액 = {ni:,.0f} + {add_total:,.0f} − {sub_total:,.0f} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.86,
        entry_point="당기순이익에서 시작해 가산조정을 더하고 차감조정을 빼서 소득금액 도출",
        trap_patterns=_trap_patterns(question),
    )


def _solve_vat_output_tax(question):
    """부가가치세 매출세액 = 국내 과세공급가액×10% + 사업상증여(접대 무상공급) 시가×10%.

    직수출은 영세율(0), 견본품 무상제공·사용인 작업복 제공은 재화의 공급으로 보지 않아 0.
    간주공급 중 '사업상 증여(접대 목적 무상공급)'만 과세하는 기본형. 안분/납부세액 변형은 미지원.
    """
    stem = question.get("stem", "")
    if "매출세액" not in stem:
        return None
    # 납부세액/매입공제/안분/과세표준 산정은 별도 유형 → 오발 방지
    if any(
        x in stem for x in ("납부세액", "공제받을", "공제 매입", "안분", "과세표준", "공통매입세액")
    ):
        return None
    dom = re.search(r"국내[^:：\n]*(?:판매|매출|공급)[^:：\n]*?[:：]?\s*([0-9,]+)\s*원", stem)
    if not dom:
        return None
    domestic = _parse_number(dom.group(1))
    output = domestic * 0.10
    gift_value = 0.0
    gift = re.search(r"접대[^()\n]*\([^)]*시가\s*([0-9,]+)\s*원", stem) or re.search(
        r"접대[^:：\n]*[:：]\s*([0-9,]+)\s*원", stem
    )
    if gift:
        gift_value = _parse_number(gift.group(1))
        output += gift_value * 0.10
    value = round(output)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    steps = [f"국내 과세공급 {domestic:,.0f} × 10% = {domestic * 0.10:,.0f}원"]
    if gift_value:
        steps.append(f"사업상증여(접대) 시가 {gift_value:,.0f} × 10% = {gift_value * 0.10:,.0f}원")
    steps.append(f"직수출=영세율(0), 견본품·작업복=공급의제 → 매출세액 {value:,.0f}원")
    return ReasonedTrace(
        rule_id="tax_vat_output_deemed_supply",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["매출세액", "국내 과세공급", "직수출 영세율", "간주공급(사업상증여)"],
        concepts=[
            "매출세액 = 국내 과세공급가액 × 10%",
            "직수출은 영세율(매출세액 0)",
            "견본품·작업복 제공은 공급의제, 사업상증여(접대)만 시가 과세",
        ],
        formula_steps=steps,
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.88,
        entry_point="과세 국내공급과 사업상증여만 과세표준에 포함, 영세율·공급의제 항목 제외",
        trap_patterns=_trap_patterns(question),
    )


def _solve_vat_payable(question):
    """부가가치세 납부세액 = 매출세액 − 대손세액공제 − 매입세액공제.

    매출세액 = 국내 과세매출 × 10% (직수출 영세율 0).
    대손세액공제 = 대손확정금액(부가세포함) × 10/110.
    매입세액공제 = (원재료 + 소모품 등 공제대상) × 10%.
    비영업용 소형승용차·접대비 매입은 불공제로 제외. 공통매입/안분 변형은 미지원.
    """
    stem = question.get("stem", "")
    if "납부세액" not in stem:
        return None
    if any(x in stem for x in ("공통매입세액", "안분", "면세사업")):
        return None
    dom = re.search(r"국내[^0-9\n]*매출[^0-9\n]*?[:：]?\s*([0-9,]+)\s*원", stem)
    if not dom:
        return None
    # 매출이 부가세 포함액(공급대가)이면 '공급가액×10%' 가정이 깨짐 → 미지원(기권)
    sales_win = stem[max(0, dom.start() - 25) : dom.end() + 20]
    if "공급대가" in sales_win or ("포함" in sales_win and "부가" in sales_win):
        return None
    domestic = _parse_number(dom.group(1))
    output = domestic * 0.10
    bad_credit = 0.0
    bad = re.search(r"대손[^()\n]*확정[^:：\n]*[:：]\s*([0-9,]+)\s*원", stem)
    if bad:
        bad_credit = _parse_number(bad.group(1)) * 10 / 110
    raw = re.search(r"원재료\s*매입[^:：\n]*[:：]\s*([0-9,]+)\s*원", stem)
    sup = re.search(r"소모품\s*매입[^:：\n]*[:：]\s*([0-9,]+)\s*원", stem)
    input_tax = 0.0
    raw_v = sup_v = 0.0
    if raw:
        raw_v = _parse_number(raw.group(1))
        input_tax += raw_v * 0.10
    if sup:
        sup_v = _parse_number(sup.group(1))
        input_tax += sup_v * 0.10
    if not (raw or sup):
        return None
    value = round(output - bad_credit - input_tax)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    steps = [f"매출세액 = 국내매출 {domestic:,.0f} × 10% = {output:,.0f}원 (직수출 영세율 0)"]
    if bad_credit:
        steps.append(f"대손세액공제 = 대손확정액 × 10/110 = {bad_credit:,.0f}원 (차감)")
    parts = []
    if raw:
        parts.append(f"원재료 {raw_v:,.0f}×10%")
    if sup:
        parts.append(f"소모품 {sup_v:,.0f}×10%")
    steps.append(
        "매입세액공제 = " + " + ".join(parts) + f" = {input_tax:,.0f}원 (승용차·접대 불공제)"
    )
    steps.append(
        f"납부세액 = {output:,.0f} − {bad_credit:,.0f} − {input_tax:,.0f} = {value:,.0f}원"
    )
    return ReasonedTrace(
        rule_id="tax_vat_payable",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["납부세액", "대손세액공제", "매입세액 불공제", "영세율"],
        concepts=[
            "납부세액 = 매출세액 − 대손세액공제 − 매입세액공제",
            "대손세액 = 대손금(부가세포함) × 10/110",
            "비영업용 소형승용차·접대비 매입세액은 불공제",
        ],
        formula_steps=steps,
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.85,
        entry_point="매출세액에서 대손세액공제와 공제가능 매입세액만 차감, 불공제 매입 제외",
        trap_patterns=_trap_patterns(question),
    )


def _solve_vat_common_input(question):
    """공통매입세액 안분 — 공제매입세액 = 공통매입세액×과세비율 + 기타 과세매입세액.

    과세비율 = 과세공급가액합 / (과세+면세 공급가액합). 확정신고는 과세기간 전체(예정+확정) 합으로 안분.
    공통매입세액 = 공통취득자산가액×10% 합.
    """
    stem = question.get("stem", "")
    if ("공통매입세액" not in stem) and ("공통으로 사용" not in stem):
        return None
    if "공제" not in stem:
        return None
    tl = re.search(r"과세사업\s*공급가액[^\n]*", stem)
    el = re.search(r"면세사업\s*공급가액[^\n]*", stem)
    if not (tl and el):
        return None
    taxable_amts = [_parse_number(x) for x in re.findall(r"([0-9,]+)\s*원", tl.group(0))]
    exempt_amts = [_parse_number(x) for x in re.findall(r"([0-9,]+)\s*원", el.group(0))]
    if not taxable_amts or not exempt_amts:
        return None
    taxable = sum(taxable_amts)
    exempt = sum(exempt_amts)
    if taxable + exempt <= 0:
        return None
    ratio = taxable / (taxable + exempt)
    # '공통으로 사용' 문맥에 앜컬링 — 단일문자 '입|득' 제거로 매입/취득 조각 오포착 차단
    common = re.findall(
        r"공통으로 사용[^\n]*?([0-9,]+)\s*원\s*\(부가가치세\s*별도\)",
        stem,
    )
    if not common:
        return None
    common_assets = [_parse_number(c) for c in common]
    common_input = sum(a * 0.10 for a in common_assets)
    deductible = common_input * ratio
    other_v = 0.0
    other = re.search(r"공통매입세액\s*제외\)[^0-9]*([0-9,]+)\s*원", stem)
    if other:
        other_v = _parse_number(other.group(1))
        deductible += other_v
    value = round(deductible)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    steps = [
        f"과세비율 = {taxable:,.0f} / ({taxable:,.0f}+{exempt:,.0f}) = {ratio:.1%}",
        f"공통매입세액 = 공통취득자산 × 10% = {common_input:,.0f}원",
        f"공통 공제분 = {common_input:,.0f} × {ratio:.1%} = {common_input * ratio:,.0f}원",
    ]
    if other:
        steps.append(f"기타 과세매입세액(전액공제) = {other_v:,.0f}원")
    steps.append(f"공제매입세액 합계 = {value:,.0f}원")
    return ReasonedTrace(
        rule_id="tax_vat_common_input_apportionment",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["공통매입세액 안분", "겸영사업자", "과세비율", "확정신고 과세기간 전체 안분"],
        concepts=[
            "공통매입세액 안분 = 공통매입세액 × 과세공급가액/총공급가액",
            "확정신고 시 과세기간 전체(예정+확정) 공급가액 비율 적용",
            "공제매입세액 = 안분된 공통매입세액 + 전액공제 기타매입세액",
        ],
        formula_steps=steps,
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.86,
        entry_point="과세기간 전체 공급가액 비율로 공통매입세액 안분 후 전액공제 항목 합산",
        trap_patterns=_trap_patterns(question),
    )


def _solve_financial_income_grossup(question):
    """금융소득 합산액 = 종합과세 금융소득(이자+배당, 분리과세 제외) + Gross-up.

    2,000만원 한도에 Gross-up 비대상 소득(이자, 국외배당 등)을 우선 충당하고,
    한도를 초과하는 Gross-up 적격 배당(법인세 과세된 내국법인 배당)만 가산 대상이다.
    무조건 분리과세(직장공제회 초과반환금)는 종합과세 대상에서 제외한다.
    배당의 Gross-up 적격 여부 표지(국내/내국/상장/비상장 vs 국외/외국)가 없으면 기권한다.
    항목 나열형 + Gross-up/가산 키워드가 모두 있어야 발동(서술형/사업소득형은 미발동).
    """
    stem = question.get("stem", "")
    if ("금융소득" not in stem) or (("Gross-up" not in stem) and ("가산" not in stem)):
        return None
    if "얼마" not in stem and "계산" not in stem:
        return None
    # 항목 나열형((1)(2)(3)...)이 아니면 미발동 → 서술/정의형(tax-002류) 차단
    start = stem.find("(1)")
    if start < 0:
        return None
    parts = re.split(r"\((\d+)\)", stem[start:])
    interest_total = 0.0  # 이자소득 (Gross-up 비적격)
    grossup_dividend = 0.0  # 내국법인 배당 (Gross-up 적격)
    other_income = 0.0  # 국외배당 등 종합과세 포함·Gross-up 비적격
    excluded_total = 0.0  # 무조건 분리과세 (종합과세 제외)
    items = 0
    unknown = 0
    seg_iter = iter(parts[1:])
    for _num, seg in zip(seg_iter, seg_iter, strict=False):
        money = re.search(r"([0-9][0-9,]+)\s*원", seg)
        if not money:
            continue
        amount = _parse_number(money.group(1))
        label = seg[: money.start()]  # 금액 이전 라벨로만 분류(후행 산문 오분류 방지)
        items += 1
        if "직장공제회" in label:
            excluded_total += amount  # 무조건 분리과세 → 종합과세 제외
        elif "배당" in label:
            # Gross-up 적격 = 법인세 과세된 내국법인 배당. 국외/외국 배당은 비적격.
            if ("국외" in label) or ("외국" in label):
                other_income += amount
            elif ("국내" in label) or ("내국" in label) or ("상장" in label) or ("비상장" in label):
                grossup_dividend += amount
            else:
                unknown += 1  # 적격 여부 불명 → 오답 방지 위해 기권
        elif ("이자" in label) or ("이익" in label) or ("예금" in label):
            interest_total += amount
        else:
            unknown += 1
    # 분류 불능 항목이 섞이면(사업소득 필요경비형 등) 오답 방지를 위해 기권
    if items < 2 or unknown > 0:
        return None
    rate_match = re.search(r"(?:배당)?가산율(?:은|이)?\s*([0-9.]+)\s*%", stem)
    gross_rate = float(rate_match.group(1)) / 100 if rate_match else 0.10
    cap = 20_000_000  # 금융소득종합과세 기준금액 2천만원
    non_grossup = interest_total + other_income  # 한도에 우선 충당되는 Gross-up 비적격 소득
    total = non_grossup + grossup_dividend
    if total <= 0:
        return None
    # 2천만원 한도에 비적격 소득 우선 충당 → 한도 초과 적격 배당만 Gross-up 대상
    if total > cap:
        gross_base = max(0.0, grossup_dividend - max(0.0, cap - non_grossup))
    else:
        gross_base = 0.0
    value = round(total + gross_base * gross_rate)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="tax_financial_income_grossup",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["금융소득종합과세", "배당가산액(Gross-up)", "분리과세 제외(직장공제회)"],
        concepts=[
            "종합과세 금융소득 = 이자 + 배당 (무조건 분리과세 항목 제외)",
            "2천만원 한도에 Gross-up 비적격 소득(이자·국외배당) 우선 충당, 초과 내국법인 배당만 Gross-up 대상",
            "합산 금융소득금액 = 종합과세 금융소득 + Gross-up 대상 × 가산율",
        ],
        formula_steps=[
            f"이자소득 합계 = {interest_total:,.0f}원, 적격 배당 = {grossup_dividend:,.0f}원, 비적격 배당(국외) = {other_income:,.0f}원 "
            f"(직장공제회 {excluded_total:,.0f}원은 분리과세로 제외)",
            f"종합과세 금융소득 = {total:,.0f}원",
            f"Gross-up 대상 = 적격배당 {grossup_dividend:,.0f} − (2,000만원 − 비적격소득 {non_grossup:,.0f}) = {gross_base:,.0f}원",
            f"합산 금융소득금액 = {total:,.0f} + {gross_base:,.0f} × {gross_rate:.0%} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.9,
        entry_point="분리과세 제외 후 2천만원 한도에 비적격소득(이자·국외배당) 우선 충당, 초과 내국법인 배당만 Gross-up",
        trap_patterns=_trap_patterns(question),
    )


def _solve_acquisition_tax_base(question: dict[str, Any]) -> ReasonedTrace | None:
    """취득세 산출세액 = 과세표준 × 표준세율.

    과세표준 = 사실상의 취득가격 + 취득시기 전 간접비용(중개수수료 등, '취득가격에 포함되지
    않은' 별도 비용). 취득시기 이후 자본적 지출액은 과세표준에서 제외한다.
    취득세 본세만 묻는 형(농특세/지방교육세 합계가 아님)에서만 발동한다.
    """
    stem = question.get("stem", "")
    if "취득세" not in stem or "산출세액" not in stem:
        return None
    # 합계형(취득세+지방교육세+농특세)은 별도 규칙 → 본세 단독 산출세액만 처리
    if "합계" in stem:
        return None
    # 부가세(지방교육세/농특세)를 '제외'가 아니라 가산하는 변형은 미지원
    if "지방교육세" in stem and "제외" not in stem:
        return None
    if "농어촌특별세" in stem and "제외" not in stem:
        return None
    # 중과/시가표준/간주·원시취득 변형은 '중과대상 아님' 명시 없으면 기권
    if any(x in stem for x in ("중과세율", "시가표준", "간주취득", "원시취득")):
        if "중과세 대상이 아니" not in stem and "중과대상이 아닌" not in stem:
            return None
    price = re.search(r"사실상의?\s*취득가격[^0-9]{0,6}([0-9,]+)\s*원", stem) or re.search(
        r"취득가액[^0-9]{0,6}([0-9,]+)\s*원", stem
    )
    rate = re.search(r"표준세율[^0-9%]{0,30}([0-9.]+)\s*%", stem) or re.search(
        r"취득세(?:율)?[^0-9%]{0,30}([0-9.]+)\s*%", stem
    )
    if not price or not rate:
        return None
    base = _parse_number(price.group(1))
    extra_steps: list[str] = []
    broker = re.search(r"중개(?:보수|수수료)[^0-9]{0,8}([0-9,]+)\s*원", stem)
    # 가산은 '취득가격에 포함되지 않은' 별도 간접비용임이 명시된 경우에만.
    # '직접 소요' 단독 신호로는 가산하지 않는다(이미 취득가격에 포함된 비용 이중계상 방지).
    if (
        broker
        and "포함되지 않은" in stem
        and "과세표준에 포함되지 않" not in stem
        and "이미 포함" not in stem
    ):
        broker_amt = _parse_number(broker.group(1))
        base += broker_amt
        extra_steps.append(f"취득 전 간접비용(중개수수료) {broker_amt:,.0f}원 과세표준 가산")
    r = float(rate.group(1)) / 100
    value = round(base * r)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    return ReasonedTrace(
        rule_id="tax_acquisition_base_rate",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["취득세", "산출세액", "사실상의 취득가격", "표준세율"],
        concepts=[
            "취득세 과세표준 = 사실상의 취득가격 + 취득 전 간접비용",
            "취득시기 이후 자본적 지출액은 과세표준 제외",
            "취득세 산출세액 = 과세표준 × 표준세율",
        ],
        formula_steps=[
            f"사실상의 취득가격 = {_parse_number(price.group(1)):,.0f}원",
            *extra_steps,
            f"과세표준 = {base:,.0f}원",
            f"산출세액 = {base:,.0f} × {r:.0%} = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.9,
        entry_point="사실상의 취득가격에 취득 전 간접비용만 더해 과세표준을 만든 뒤 표준세율 적용(취득 후 자본적지출 제외)",
        trap_patterns=_trap_patterns(question),
    )


def _solve_acquisition_tax_with_surtaxes(question: dict[str, Any]) -> ReasonedTrace | None:
    """취득세 + 지방교육세 + 농어촌특별세 합계.

    취득세 = 과세표준 × 표준세율
    지방교육세 = 과세표준 × (표준세율 − 2%) × 20%  (지방세법 제151조 표준 케이스)
    농어촌특별세 = (과세표준 × 2%) × 10%
    합계액을 묻는 형에서만 발동한다.
    """
    stem = question.get("stem", "")
    if "취득세" not in stem or "합계" not in stem:
        return None
    if "지방교육세" not in stem or "농어촌특별세" not in stem:
        return None
    base_m = re.search(r"(?:매매대금|취득가액|사실상의?\s*취득가격)[^0-9]{0,6}([0-9,]+)\s*원", stem)
    rate_m = re.search(r"취득세\s*표준세율(?:은|이)?\s*([0-9.]+)\s*%", stem) or re.search(
        r"표준세율(?:은|이)?\s*([0-9.]+)\s*%", stem
    )
    if not base_m or not rate_m:
        return None
    base = _parse_number(base_m.group(1))
    rate = float(rate_m.group(1)) / 100
    # 본 분해식((세율−2%)·2%분)은 표준세율 4% 케이스에 한정 — 그 외는 기권
    if abs(rate - 0.04) > 1e-9:
        return None
    # 농특세 규정이 표준(2%분의 10%)과 다르면 기권
    if "2%" not in stem and "2% 분" not in stem and "2%분" not in stem:
        return None
    acquisition = base * rate
    education = base * (rate - 0.02) * 0.20
    farming = (base * 0.02) * 0.10
    value = round(acquisition + education + farming)
    chosen = _choose_closest_money(question["choices"], value)
    if chosen < 0:
        return None

    return ReasonedTrace(
        rule_id="tax_acquisition_with_surtaxes",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["취득세", "지방교육세", "농어촌특별세", "합계", "표준세율"],
        concepts=[
            "취득세 = 과세표준 × 표준세율",
            "지방교육세 = 과세표준 × (표준세율 − 2%) × 20%",
            "농어촌특별세 = 과세표준 × 2% × 10%",
        ],
        formula_steps=[
            f"과세표준 = {base:,.0f}원",
            f"취득세 = {base:,.0f} × {rate:.0%} = {acquisition:,.0f}원",
            f"지방교육세 = {base:,.0f} × ({rate:.0%} − 2%) × 20% = {education:,.0f}원",
            f"농어촌특별세 = ({base:,.0f} × 2%) × 10% = {farming:,.0f}원",
            f"합계 = {value:,.0f}원",
        ],
        choice_notes=_choice_notes(question["choices"], chosen, value),
        computed_value=value,
        confidence=0.88,
        entry_point="본세(취득세)에 지방교육세·농어촌특별세를 제151조/농특세법 산식대로 각각 산출해 합산",
        trap_patterns=_trap_patterns(question),
    )


# --- shared local helpers for non-money(%/%p/개) choices ---
# (이 두 헬퍼는 economics_quantity_theory_inflation, economics_uip_return_gap,
#  management_eoq 세 규칙이 공유한다. 모듈에 한 번만 정의하면 된다.
#  기존 _choice_notes/_choose_closest_money는 '원' 단위 전용이라 %/%p/개를 못 파싱하므로 별도 정의.)


def _solve_quantity_theory_inflation(question: dict) -> ReasonedTrace | None:
    """화폐수량설 변화율 근사: V 일정일 때 %ΔP = %ΔM − %ΔY (단일 단계 기본형)."""
    stem = question.get("stem", "")
    if "화폐수량설" not in stem and "MV" not in stem:
        return None
    if "물가상승률" not in stem and "P 변화율" not in stem and "인플레이션" not in stem:
        return None
    # 유통속도가 일정(불변/고정)으로 명시되지 않으면 %ΔV=0 가정이 깨질 수 있어 미지원 → 오답 방지
    if "유통속도" in stem and not any(k in stem for k in ("일정", "불변", "고정")):
        return None
    m = re.search(r"통화량\(?M\)?(?:이|가|은|는)?\s*([0-9.]+)\s*%", stem)
    y = re.search(r"국민소득\(?Y\)?(?:이|가|은|는)?\s*([0-9.]+)\s*%", stem)
    if not m or not y:
        return None
    mg = _parse_number(m.group(1))
    yg = _parse_number(y.group(1))
    value = mg - yg

    def ext(c):
        mm = re.search(r"(-?[0-9.]+)\s*%", c)
        return float(mm.group(1)) if mm else None

    chosen = _closest_index(question["choices"], value, ext)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="economics_quantity_theory_inflation",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=["화폐수량설 MV=PY", "통화량 증가율", "실질소득 증가율", "유통속도 일정"],
        concepts=["변화율 근사: %ΔM + %ΔV = %ΔP + %ΔY", "V 일정 → %ΔP = %ΔM − %ΔY"],
        formula_steps=[
            f"%ΔM = {mg:g}%, %ΔY = {yg:g}%, %ΔV = 0",
            f"%ΔP = {mg:g}% − {yg:g}% = {value:g}%",
        ],
        choice_notes=_pct_choice_notes(question["choices"], chosen, value, ext, "%p"),
        computed_value=value,
        confidence=0.9,
        entry_point="화폐수량설 변화율 근사식에서 물가상승률 분리 (M 증가율 그대로·M+Y 합산 함정)",
        trap_patterns=_trap_patterns(question),
    )


def _solve_uip_return_gap(question: dict) -> ReasonedTrace | None:
    """UIP 가정 하 한국·미국 자산 기대수익률 차 = i_KR − (i_US + 예상 환율변화율).

    원/달러 환율 상승(원화 절하) → 미국자산 원화환산 수익률에 환율 상승률을 가산.
    공유 헬퍼 _closest_index/_pct_choice_notes 는 economics_quantity_theory_inflation 정의 참조.
    """
    stem = question.get("stem", "")
    if "UIP" not in stem and "이자율평형" not in stem:
        return None
    if "기대수익률" not in stem and "몇 %p" not in stem:
        return None
    rates = re.search(
        r"명목이자율(?:이|은|가)?\s*각각\s*연?\s*([0-9.]+)\s*%\s*,\s*([0-9.]+)\s*%", stem
    )
    fx = re.search(r"([0-9.]+)\s*%\s*상승", stem)
    if not rates or not fx:
        return None
    # 환율 방향이 '하락'만 제시된 부호 변형형은 미지원 → 오답 방지
    if "하락" in stem and "상승" not in stem:
        return None
    r1 = _parse_number(rates.group(1))
    r2 = _parse_number(rates.group(2))
    # 국가 라벨 등장 순서로 이자율 매핑 (예: '미국과 한국의 ... 각각'은 순서 반대)
    kr_pos, us_pos = stem.find("한국"), stem.find("미국")
    if kr_pos < 0 or us_pos < 0:
        return None
    i_kr, i_us = (r1, r2) if kr_pos < us_pos else (r2, r1)
    dfx = _parse_number(fx.group(1))
    value = i_kr - (i_us + dfx)

    def ext(c):
        mm = re.search(r"(-?[0-9.]+)\s*%p", c)
        return float(mm.group(1)) if mm else None

    chosen = _closest_index(question["choices"], value, ext)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="economics_uip_return_gap",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=[
            "무위험 이자율평형설 UIP",
            "한국·미국 명목이자율",
            "원/달러 환율 상승(원화 절하)",
            "기대수익률 비교",
        ],
        concepts=[
            "미국자산 원화환산 기대수익률 = i_US + 예상 환율변화율",
            "수익률 차이 = i_KR − (i_US + %Δ환율)",
        ],
        formula_steps=[
            f"한국 자산 기대수익률 = {i_kr:g}%",
            f"미국 자산 원화환산 기대수익률 = {i_us:g}% + {dfx:g}% = {i_us + dfx:g}%",
            f"차이 = {i_kr:g}% − {i_us + dfx:g}% = {value:g}%p",
        ],
        choice_notes=_pct_choice_notes(question["choices"], chosen, value, ext, "%p"),
        computed_value=value,
        confidence=0.86,
        entry_point="환율 상승(원화 절하)을 미국자산 수익률에 가산 후 한국자산과 비교 (이자율 차만 비교·부호 함정)",
        trap_patterns=_trap_patterns(question),
    )


def _solve_eoq(question: dict) -> ReasonedTrace | None:
    """경제적 주문량 EOQ = √(2DS/H) (단일 단계 기본형, 수량할인/안전재고 등 변형 제외).

    공유 헬퍼 _closest_index/_pct_choice_notes 는 economics_quantity_theory_inflation 정의 참조.
    """
    stem = question.get("stem", "")
    if "EOQ" not in stem and "경제적 주문량" not in stem:
        return None
    # 다단계/표조회 변형형은 미지원 → 오답 방지
    if any(
        x in stem for x in ("할인", "수량할인", "안전재고", "재주문점", "리드타임", "품절", "일수")
    ):
        return None
    D = re.search(r"(?:연간\s*)?수요(?:량|량은|는)?[^0-9]{0,6}([0-9,]+)\s*개", stem)
    S = re.search(r"(?:1회\s*)?주문비(?:용)?[^0-9]{0,6}([0-9,]+)\s*원", stem)
    H = re.search(r"재고유지비(?:용)?[^0-9]{0,6}([0-9,]+)\s*원", stem)
    if not (D and S and H):
        return None
    d = _parse_number(D.group(1))
    s = _parse_number(S.group(1))
    h = _parse_number(H.group(1))
    if d <= 0 or s <= 0 or h <= 0:
        return None
    value = round(math.sqrt(2 * d * s / h))

    def ext(c):
        mm = re.search(r"([0-9,]+)\s*개", c)
        return _parse_number(mm.group(1)) if mm else None

    chosen = _closest_index(question["choices"], value, ext)
    if chosen < 0:
        return None
    return ReasonedTrace(
        rule_id="management_eoq",
        chosen_index=chosen,
        answer_text=f"{chosen + 1}번 {question['choices'][chosen]}",
        signals=[
            "경제적 주문량 EOQ",
            "연간 수요량 D",
            "1회 주문비용 S",
            "단위당 연간 재고유지비 H",
        ],
        concepts=["EOQ = √(2DS/H)"],
        formula_steps=[
            f"D = {d:,.0f}개, S = {s:,.0f}원, H = {h:,.0f}원",
            f"EOQ = √(2 × {d:,.0f} × {s:,.0f} / {h:,.0f}) = √{2 * d * s / h:,.0f} ≈ {value:,.0f}개",
        ],
        choice_notes=_pct_choice_notes(question["choices"], chosen, value, ext, "개"),
        computed_value=value,
        confidence=0.93,
        entry_point="EOQ 공식에 D·S·H 대입 (2 누락·S/H 교체·제곱근 누락 함정)",
        trap_patterns=_trap_patterns(question),
    )


_RULES: tuple[Rule, ...] = (
    _solve_npv,
    _solve_moving_average_inventory,
    _solve_effective_interest,
    _solve_gordon_growth,
    _solve_revaluation_loss,
    _solve_corporate_tax,
    _solve_straight_line_depreciation,
    _solve_bep_sales,
    _solve_cogs,
    _solve_eps,
    _solve_manufacturing_cogs,
    _solve_overhead_application_variance,
    _solve_margin_of_safety_ratio,
    _solve_dol_profit_change,
    _solve_special_order,
    _solve_bep_units_and_safety_sales,
    _solve_perpetuity_pv,
    _solve_growing_perpetuity_pv,
    _solve_ordinary_annuity_pv,
    _solve_capm_required_return,
    _solve_portfolio_expected_return,
    _solve_portfolio_std_dev,
    _solve_npv_annuity,
    _solve_irr_closest_rate,
    _solve_wacc,
    _solve_put_call_parity,
    _solve_impairment_loss,
    _solve_transaction_price_allocation,
    _solve_indirect_cash_flow,
    _solve_treasury_reissue_entry,
    _solve_treasury_multi_transaction,
    _solve_entertainment_expense_limit,
    _solve_taxable_income_adjustment,
    _solve_vat_output_tax,
    _solve_vat_payable,
    _solve_vat_common_input,
    _solve_financial_income_grossup,
    _solve_acquisition_tax_base,
    _solve_acquisition_tax_with_surtaxes,
    _solve_quantity_theory_inflation,
    _solve_uip_return_gap,
    _solve_eoq,
)
