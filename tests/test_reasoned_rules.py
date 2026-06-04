"""결정론 reasoned solver 신규 규칙 단위 테스트 (정액법 감가상각, 손익분기점 매출액)."""

from __future__ import annotations

import json
import pathlib
from pathlib import Path

from cpa_first.solver.reasoned import (
    _solve_put_call_parity,
    _solve_wacc,
    solve_reasoned,
)


def _q(qid, stem, choices):
    return {
        "question_id": qid,
        "subject": "accounting",
        "unit": "test",
        "stem": stem,
        "choices": choices,
    }


def test_straight_line_depreciation():
    q = _q(
        "sl-1",
        "㈜한국은 2026년 초 기계장치를 취득하였다. 취득원가 1,000,000원, "
        "내용연수 5년, 잔존가치 100,000원, 정액법으로 감가상각한다. 연 감가상각비는?",
        ["150,000원", "180,000원", "200,000원", "220,000원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "accounting_straight_line_depreciation"
    assert res.chosen_index == 1  # (1,000,000-100,000)/5 = 180,000


def test_straight_line_skips_accumulated():
    # 감가상각누계액은 미지원 → 다른 규칙/기권으로 빠져야 함 (정액법 규칙 미발동)
    q = _q(
        "sl-2",
        "취득원가 1,000,000원, 내용연수 5년, 잔존가치 0원, 정액법. 3년 경과 후 감가상각누계액은?",
        ["400,000원", "600,000원", "800,000원", "1,000,000원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "accounting_straight_line_depreciation"


def test_bep_sales():
    q = _q(
        "bep-1",
        "㈜대한의 연간 고정비는 3,000,000원이고 공헌이익률은 30%이다. "
        "손익분기점 매출액은 얼마인가?",
        ["7,000,000원", "9,000,000원", "10,000,000원", "12,000,000원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "cost_bep_sales"
    assert res.chosen_index == 2  # 3,000,000 / 0.30 = 10,000,000


def test_cogs():
    q = _q(
        "cogs-1",
        "㈜한국의 기초상품재고는 200,000원, 당기순매입액은 1,500,000원, "
        "기말상품재고는 300,000원이다. 매출원가는 얼마인가?",
        ["1,300,000원", "1,400,000원", "1,500,000원", "1,600,000원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "accounting_cogs"
    assert res.chosen_index == 1  # 200,000 + 1,500,000 − 300,000 = 1,400,000


def test_cogs_skips_complex():
    # 평가손실/감모 등 복잡형은 규칙 미발동 (오답 방지)
    q = _q(
        "cogs-2",
        "기초재고 200,000원, 당기매입 1,500,000원, 기말재고 300,000원이며 "
        "재고자산평가손실 50,000원이 발생했다. 매출원가는?",
        ["1,400,000원", "1,450,000원", "1,500,000원", "1,350,000원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "accounting_cogs"


def test_eps():
    q = _q(
        "eps-1",
        "㈜대한의 당기순이익은 11,000,000원, 우선주배당금은 1,000,000원이며 "
        "가중평균유통보통주식수는 10,000주이다. 기본주당순이익(EPS)은?",
        ["900원", "1,000원", "1,100원", "1,200원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "accounting_eps"
    assert res.chosen_index == 1  # (11,000,000 − 1,000,000) / 10,000 = 1,000


def test_rule_does_not_misfire_on_unrelated():
    # 계산 신호 없는 개념형 문항엔 신규 계산 규칙이 발동하지 않음
    q = _q(
        "u-1",
        "다음 중 무형자산으로 분류할 수 없는 것은?",
        ["영업권", "특허권", "재고자산", "상표권"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] not in {
        "accounting_straight_line_depreciation",
        "cost_bep_sales",
        "accounting_cogs",
        "accounting_eps",
    }


import pytest  # noqa: E402

_EVAL_DIR = Path(__file__).resolve().parents[1] / "data" / "seeds" / "evaluation"

# 실제 평가셋에서 결정론 공식 규칙이 '정답키 폴백 없이' 직접 푸는 문항 (qid, 기대 rule_id)
_GENUINE_SOLVES = [
    ("cpa1-eval-accounting-003", "cost_bep_units_and_safety_sales"),
    ("cpa1-eval-accounting-004", "accounting_impairment_loss"),
    ("cpa1-eval-accounting-005", "accounting_transaction_price_allocation"),
    ("cpa1-eval-accounting-007", "accounting_indirect_cash_flow"),
    ("cpa1-eval-accounting-008", "accounting_treasury_reissue_entry"),
    ("cpa1-eval-accounting-031", "cost_manufacturing_flow"),
    ("cpa1-eval-accounting-032", "cost_overhead_application_variance"),
    ("cpa1-eval-accounting-035", "cost_margin_of_safety_ratio"),
    ("cpa1-eval-accounting-036", "cost_dol_profit_change"),
    ("cpa1-eval-accounting-042", "accounting_treasury_multi_transaction"),
    ("cpa1-eval-accounting-046", "cost_special_order_profit"),
    ("cpa1-eval-business-002", "finance_perpetuity_pv"),
    ("cpa1-eval-business-003", "finance_growing_perpetuity_pv"),
    ("cpa1-eval-business-004", "finance_ordinary_annuity_pv"),
    ("cpa1-eval-business-005", "finance_capm_required_return"),
    ("cpa1-eval-business-006", "finance_portfolio_expected_return"),
    ("cpa1-eval-business-007", "finance_portfolio_std_dev"),
    ("cpa1-eval-business-008", "finance_npv_annuity_factor"),
    ("cpa1-eval-business-009", "finance_irr_closest_rate"),
    ("cpa1-eval-business-012", "finance_wacc"),
    ("cpa1-eval-business-015", "finance_put_call_parity"),
    ("cpa1-eval-economics-014", "economics_quantity_theory_inflation"),
    ("cpa1-eval-economics-015", "economics_uip_return_gap"),
    ("cpa1-eval-management-013", "management_eoq"),
    ("cpa1-eval-tax-007", "tax_vat_payable"),
    ("cpa1-eval-tax-008", "tax_financial_income_grossup"),
    ("cpa1-eval-tax-015", "tax_taxable_income_adjustment"),
    ("cpa1-eval-tax-016", "tax_entertainment_expense_limit"),
    ("cpa1-eval-tax-022", "tax_vat_output_deemed_supply"),
    ("cpa1-eval-tax-024", "tax_vat_common_input_apportionment"),
    ("cpa1-eval-tax-031", "tax_acquisition_base_rate"),
    ("cpa1-eval-tax-032", "tax_acquisition_with_surtaxes"),
    ("cpa1-eval-tax-033", "tax_financial_income_grossup"),
]


@pytest.mark.parametrize("qid,rule_id", _GENUINE_SOLVES)
def test_reasoned_genuinely_solves_real_eval_question(qid, rule_id):
    """공식 규칙이 발동(known_solution_bank 아님)하고 정답을 맞히는지 — 실데이터 회귀."""
    q = json.loads((_EVAL_DIR / f"{qid}.evaluation_question.json").read_text(encoding="utf-8"))
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == rule_id, "정답키 폴백/오발 — 진짜 풀이 아님"
    assert res.chosen_index == q["correct_choice"], "공식 계산이 정답과 불일치"


def test_manufacturing_cost_flow_cogs():
    q = _q(
        "mfg-1",
        "기초재공품 80,000원, 직접재료원가 220,000원, 직접노무원가 180,000원, "
        "제조간접원가 150,000원, 기말재공품 110,000원, 기초제품재고 40,000원, "
        "기말제품재고 70,000원이다. 매출원가는 얼마인가?",
        ["490,000원", "520,000원", "550,000원", "580,000원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "cost_manufacturing_flow"
    # COGM=80,000+550,000-110,000=520,000; COGS=40,000+520,000-70,000=490,000
    assert res.chosen_index == 0


def test_manufacturing_flow_skips_simple_and_adjusted():
    # 재공품 단계 없는 단순 상품 매출원가 → 제조원가 3분법 규칙 미발동
    q_simple = _q(
        "mfg-2",
        "기초상품재고 200,000원, 당기매입 1,500,000원, 기말상품재고 300,000원이다. 매출원가는?",
        ["1,300,000원", "1,400,000원", "1,500,000원", "1,600,000원"],
    )
    assert solve_reasoned(q_simple).tool_calls[0]["rule_id"] != "cost_manufacturing_flow"
    # 배부차이 조정 변형형도 미발동
    q_adj = _q(
        "mfg-3",
        "기초재공품 80,000원, 직접재료원가 220,000원, 직접노무원가 180,000원, "
        "제조간접원가 150,000원, 기말재공품 110,000원, 기초제품 40,000원, "
        "기말제품 70,000원, 배부차이 조정 후 매출원가는?",
        ["490,000원", "520,000원", "550,000원", "580,000원"],
    )
    assert solve_reasoned(q_adj).tool_calls[0]["rule_id"] != "cost_manufacturing_flow"


def test_overhead_application_variance_underapplied():
    q = _q(
        "oh-1",
        "정상개별원가계산을 적용하며, 제조간접원가는 직접노무시간 기준으로 예정배부한다. "
        "예정 제조간접원가 600,000원, 예정 직접노무시간 30,000시간, "
        "실제 제조간접원가 700,000원, 실제 직접노무시간 32,000시간이다. "
        "제조간접원가 배부차이는 얼마인가?",
        ["과대배부 40,000원", "과소배부 40,000원", "과대배부 60,000원", "과소배부 60,000원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "cost_overhead_application_variance"
    # 예정배부율 @20, 예정배부액 640,000, 차이 60,000 과소배부 -> index 3 (금액+부호 동시 일치)
    assert res.chosen_index == 3


def test_overhead_variance_overapplied_sign():
    # 실제 < 예정배부 → 과대배부 방향으로 선택되어야 함 (부호 인식 검증)
    q = _q(
        "oh-2",
        "제조간접원가는 직접노무시간 기준으로 예정배부한다. 예정 제조간접원가 600,000원, "
        "예정 직접노무시간 30,000시간, 실제 제조간접원가 500,000원, "
        "실제 직접노무시간 28,000시간이다. 제조간접원가 배부차이는?",
        ["과대배부 40,000원", "과소배부 40,000원", "과대배부 60,000원", "과소배부 60,000원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "cost_overhead_application_variance"
    # 예정배부액 28,000*20=560,000; 차이 500,000-560,000=-60,000 과대배부 -> index 2
    assert res.chosen_index == 2


def test_margin_of_safety_ratio():
    q = {
        "question_id": "mos-1",
        "subject": "accounting",
        "unit": "cvp",
        "stem": "㈜CF의 20X1년 매출액은 5,000,000원, 변동원가 3,000,000원, 고정원가 1,200,000원이다. "
        "안전한계율(margin of safety ratio)은 얼마인가?",
        "choices": ["20%", "40%", "60%", "70%"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "cost_margin_of_safety_ratio"
    assert res.chosen_index == 1


def test_margin_of_safety_skips_unit_variant():
    q = {
        "question_id": "mos-2",
        "subject": "accounting",
        "unit": "cvp",
        "stem": "단위당 판매가 1,000원, 단위당 변동원가 600원, 고정원가 200,000원일 때 안전한계율은?",
        "choices": ["20%", "40%", "60%", "70%"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "cost_margin_of_safety_ratio"


def test_dol_profit_change():
    q = {
        "question_id": "dol-1",
        "subject": "accounting",
        "unit": "cvp",
        "stem": "㈜CF의 당기 영업이익은 400,000원이며 공헌이익은 1,200,000원이다. "
        "다음 기에 매출이 10% 증가하면 영업이익은 몇 % 증가하는가?",
        "choices": ["10%", "20%", "30%", "33%"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "cost_dol_profit_change"
    assert res.chosen_index == 2


def test_special_order_profit():
    q = {
        "question_id": "so-1",
        "subject": "accounting",
        "unit": "cvp",
        "stem": "단위당 변동원가 120원, 연간 고정원가 800,000원이다. 외부 고객으로부터 5,000단위를 "
        "단위당 150원에 특별주문 받았다. 유휴생산능력은 충분하며 추가 고정원가는 발생하지 않는다. "
        "특별주문 수락 시 영업이익은 얼마나 변동하는가?",
        "choices": ["100,000원 감소", "150,000원 증가", "250,000원 증가", "750,000원 증가"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "cost_special_order_profit"
    assert res.chosen_index == 1


def test_special_order_skips_without_guard_phrase():
    q = {
        "question_id": "so-2",
        "subject": "accounting",
        "unit": "cvp",
        "stem": "단위당 변동원가 120원인 제품에 5,000단위를 단위당 150원에 특별주문 받았다. 영업이익 변동은?",
        "choices": ["100,000원 감소", "150,000원 증가", "250,000원 증가", "750,000원 증가"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "cost_special_order_profit"


def test_bep_units_and_safety_sales():
    q = {
        "question_id": "bep-pair-1",
        "subject": "accounting",
        "unit": "cvp",
        "stem": "단일 제품의 단위당 판매가격은 5,000원, 단위당 변동비는 3,000원, 연간 고정비는 4,000,000원이다. "
        "손익분기점 판매량(BEP)과 안전한계율(20%일 때 매출액)을 묶은 짝으로 옳은 것은?",
        "choices": [
            "BEP 1,600개 / 안전한계 매출액 10,000,000원",
            "BEP 2,000개 / 안전한계 매출액 12,500,000원",
            "BEP 2,000개 / 안전한계 매출액 2,000,000원",
            "BEP 2,500개 / 안전한계 매출액 10,000,000원",
        ],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "cost_bep_units_and_safety_sales"
    assert res.chosen_index == 1


def test_plain_bep_sales_still_routes_to_existing_rule():
    q = {
        "question_id": "bep-plain",
        "subject": "accounting",
        "unit": "cvp",
        "stem": "연간 고정비는 3,000,000원이고 공헌이익률은 30%이다. 손익분기점 매출액은 얼마인가?",
        "choices": ["7,000,000원", "9,000,000원", "10,000,000원", "12,000,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "cost_bep_sales"


def test_perpetuity_pv():
    q = {
        "question_id": "perp-1",
        "subject": "business",
        "unit": "financial_management",
        "stem": "매년 말 200,000원씩 영구히 지급되는 영구연금(Perpetuity)이 있다. "
        "할인율이 연 8%일 때 이 영구연금의 현재가치는 얼마인가?",
        "choices": ["1,250,000원", "2,000,000원", "2,500,000원", "16,000,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "finance_perpetuity_pv"
    assert res.chosen_index == 2  # 200,000 / 0.08 = 2,500,000


def test_perpetuity_skips_growing():
    # 성장영구연금은 단순 영구연금 규칙이 발동하면 안 됨 (분모가 k-g)
    q = {
        "question_id": "perp-2",
        "subject": "business",
        "unit": "financial_management",
        "stem": "매년 말 1,000,000원씩 매년 5%씩 지급액이 증가하는 성장영구연금이 있다. "
        "할인율은 연 10%이다. 현재가치는?",
        "choices": ["10,000,000원", "15,000,000원", "20,000,000원", "25,000,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "finance_perpetuity_pv"


def test_growing_perpetuity_pv():
    q = {
        "question_id": "gperp-1",
        "subject": "business",
        "unit": "financial_management",
        "stem": "매년 말 1,000,000원씩 5년간 지급되고, 첫 지급 직후부터 매년 5%씩 "
        "지급액이 증가하는 성장영구연금이 있다. 첫 지급은 1년 뒤에 발생하며, "
        "할인율은 연 10%이다. 이 성장영구연금의 현재가치는 얼마인가?",
        "choices": ["10,000,000원", "15,000,000원", "20,000,000원", "25,000,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "finance_growing_perpetuity_pv"
    assert res.chosen_index == 2  # 1,000,000 / (0.10 - 0.05) = 20,000,000


def test_growing_perpetuity_skips_when_k_le_g():
    # 할인율 <= 성장률이면 발산 → 규칙 기권 (오답 방지)
    q = {
        "question_id": "gperp-2",
        "subject": "business",
        "unit": "financial_management",
        "stem": "매년 말 1,000,000원씩 매년 12%씩 지급액이 증가하는 성장영구연금이 있다. "
        "할인율은 연 10%이다. 현재가치는?",
        "choices": ["10,000,000원", "20,000,000원", "30,000,000원", "40,000,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "finance_growing_perpetuity_pv"


def test_ordinary_annuity_pv():
    q = {
        "question_id": "annu-1",
        "subject": "business",
        "unit": "financial_management",
        "stem": "오늘부터 매년 말 300,000원씩 4년간 지급되는 정상연금이 있다. "
        "할인율이 연 10%일 때, 이 정상연금의 현재가치는 약 얼마인가? "
        "(1.1^4 = 1.4641, 연금현가요소 PVA(10%, 4년) ≈ 3.1699)",
        "choices": ["950,970원", "1,000,000원", "1,200,000원", "1,300,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "finance_ordinary_annuity_pv"
    assert res.chosen_index == 0  # 300,000 × 3.1699 = 950,970


def test_ordinary_annuity_skips_without_factor():
    # PVA 계수가 명시되지 않으면 계수 자체 계산을 피하고 기권
    q = {
        "question_id": "annu-2",
        "subject": "business",
        "unit": "financial_management",
        "stem": "매년 말 300,000원씩 4년간 지급되는 정상연금이 있다. "
        "할인율이 연 10%일 때 현재가치는?",
        "choices": ["950,970원", "1,000,000원", "1,200,000원", "1,300,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "finance_ordinary_annuity_pv"


def test_capm_required_return():
    q = {
        "question_id": "capm-1",
        "subject": "business",
        "unit": "financial_management",
        "stem": "주식 A의 베타는 1.4이다. 무위험이자율은 연 3%, 시장포트폴리오의 "
        "기대수익률은 연 9%이다. CAPM에 의한 주식 A의 요구수익률은 얼마인가?",
        "choices": ["8.4%", "11.4%", "12.6%", "15.6%"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "finance_capm_required_return"
    assert res.chosen_index == 1  # 3 + 1.4*(9-3) = 11.4%


def test_capm_skips_portfolio_composition():
    # 비중이 있는 포트폴리오 구성 문항엔 CAPM 규칙 미발동
    q = {
        "question_id": "capm-2",
        "subject": "business",
        "unit": "financial_management",
        "stem": "X의 비중은 60%, Y는 40%이다. X의 기대수익률은 12%, Y는 8%이다. "
        "이 포트폴리오의 기대수익률은?",
        "choices": ["9.6%", "10.0%", "10.4%", "11.2%"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "finance_capm_required_return"


def test_portfolio_expected_return():
    q = {
        "question_id": "pret-1",
        "subject": "business",
        "unit": "financial_management",
        "stem": "포트폴리오는 주식 X와 Y로 구성된다. X의 비중은 60%, Y는 40%이다. "
        "X의 기대수익률은 12%, Y는 8%이다. X와 Y의 표준편차는 각각 20%, 10%이며 "
        "수익률 상관계수는 0.5이다. 이 포트폴리오의 기대수익률은?",
        "choices": ["9.6%", "10.0%", "10.4%", "11.2%"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "finance_portfolio_expected_return"
    assert res.chosen_index == 2  # 0.6*12 + 0.4*8 = 10.4%


def test_portfolio_expected_return_skips_std_question():
    # 표준편차를 묻는 문항엔 기대수익률 규칙 미발동
    q = {
        "question_id": "pret-2",
        "subject": "business",
        "unit": "financial_management",
        "stem": "주식 X와 Y에 각각 50%씩 투자한 포트폴리오가 있다. X와 Y의 표준편차는 "
        "각각 20%, 10%이고 수익률 상관계수는 -1이다. 이 포트폴리오의 표준편차는?",
        "choices": ["0%", "5%", "10%", "15%"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "finance_portfolio_expected_return"


def test_portfolio_std_dev():
    q = {
        "question_id": "pstd-1",
        "subject": "business",
        "unit": "financial_management",
        "stem": "주식 X와 Y에 각각 50%씩 투자한 포트폴리오가 있다. X와 Y의 표준편차는 "
        "각각 20%, 10%이고 수익률 상관계수는 -1이다. 이 포트폴리오의 표준편차는?",
        "choices": ["0%", "5%", "10%", "15%"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "finance_portfolio_std_dev"
    assert res.chosen_index == 1  # sqrt(0.0025) = 5%


def test_portfolio_std_dev_skips_expected_return_question():
    # 기대수익률을 묻는 포트폴리오 문항엔 표준편차 규칙 미발동
    q = {
        "question_id": "pstd-2",
        "subject": "business",
        "unit": "financial_management",
        "stem": "포트폴리오는 주식 X와 Y로 구성된다. X의 비중은 60%, Y는 40%이다. "
        "X의 기대수익률은 12%, Y는 8%이다. 이 포트폴리오의 기대수익률은?",
        "choices": ["9.6%", "10.0%", "10.4%", "11.2%"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "finance_portfolio_std_dev"


def test_npv_annuity_factor():
    q = _q(
        "npv-pva-1",
        "투자안 B는 오늘 800,000원을 투자하면 3년간 매년 말 320,000원의 현금흐름이 발생한다. "
        "할인율 10%일 때 투자안 B의 NPV는 약 얼마인가? (PVA(10%, 3년) ≈ 2.4869)",
        ["-204,192원", "-160,000원", "0원", "-4,192원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "finance_npv_annuity_factor"
    assert res.chosen_index == 3  # 320,000×2.4869 − 800,000 = -4,192


def test_npv_annuity_skips_plain_flows():
    # PVA 계수 명시 없는 연도별 현금흐름 NPV는 annuity 규칙 미발동(기존 _solve_npv 담당)
    q = _q(
        "npv-plain-1",
        "오늘 100,000원을 투자하면 1년 뒤 60,000원, 2년 뒤 60,000원이 발생한다. 할인율이 10%일 때 NPV는?",
        ["4,132원", "14,876원", "20,000원", "104,132원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "finance_npv_annuity_factor"


def test_irr_closest_rate():
    q = _q(
        "irr-1",
        "오늘 1,000,000원을 투자하면 1년 뒤 600,000원, 2년 뒤 600,000원이 발생하는 "
        "투자안의 내부수익률(IRR)은 다음 중 가장 가까운 것은?",
        ["10%", "13%", "20%", "25%"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "finance_irr_closest_rate"
    assert res.chosen_index == 1  # r=13%에서 NPV≈0 (최소 |NPV|)


def test_irr_skips_definition_form():
    # 현금흐름·초기투자 없는 정의형/서술형 보기는 기권 (억지 계산 금지)
    q = _q(
        "irr-2",
        "다음 중 내부수익률(IRR)에 관한 설명으로 올바른 것은?",
        [
            "NPV를 0으로 만드는 할인율이다",
            "항상 유일하게 존재한다",
            "할인율과 무관하다",
            "회수기간과 같다",
        ],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "finance_irr_closest_rate"


def test_wacc_rule_business_012():
    q = {
        "question_id": "cpa1-eval-business-012",
        "stem": "ㅢCF의 자본구조는 자기자본 60%, 부채 40%이다. 자기자본비용 15%, 세전 부채비용 8%, 법인세율 25%이다. ㅢCF의 가중평균자본비용(WACC)은 얼마인가?",
        "choices": ["9.0%", "11.4%", "12.0%", "13.0%"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "finance_wacc"
    assert res.chosen_index == 1


def test_wacc_rule_skips_capm_variant():
    q = {
        "question_id": "x",
        "stem": "자기자본비용은 CAPM(베타 1.2, 시장위험프리미엄 6%)으로 산출하고 WACC를 구하라.",
        "choices": ["9.0%", "11.4%", "12.0%", "13.0%"],
    }
    assert _solve_wacc(q) is None


def test_put_call_parity_rule_business_015():
    q = {
        "question_id": "cpa1-eval-business-015",
        "stem": "유럽형 콜옵션과 풋옵션의 행사가격은 모두 100,000원, 만기는 1년이다. 현재 기초자산 가격은 95,000원, 무위험이자율은 연 5%(연속복리 아님). 콜옵션 가격이 8,000원일 때, 풋콜패리티에 의한 풋옵션의 이론가격은 얼마인가?",
        "choices": ["3,000원", "8,238원", "13,000원", "18,238원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "finance_put_call_parity"
    assert res.chosen_index == 1


def test_put_call_parity_skips_dividend_variant():
    q = {
        "question_id": "x",
        "stem": "배당이 있는 기초자산의 풋콜패리티로 풋옵션 가격을 구하라. 행사가격 100,000원...",
        "choices": ["3,000원", "8,238원"],
    }
    assert _solve_put_call_parity(q) is None


def test_impairment_loss():
    q = _q(
        "imp-1",
        "㈜한국은 20X1년 1월 1일 기계장치를 1,000,000원에 취득하였다. 내용연수 5년, "
        "잔존가치 100,000원, 정액법 적용. 20X3년 1월 1일 손상 신호가 발생하여 회수가능액을 "
        "측정한 결과 사용가치 360,000원, 순공정가치 400,000원이었다. 손상차손은?",
        ["240,000원", "280,000원", "320,000원", "640,000원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "accounting_impairment_loss"
    assert res.chosen_index == 0  # 장부 640,000 − 회수가능 400,000 = 240,000


def test_impairment_skips_revaluation():
    # 재평가모형 변형은 미지원 → 손상 규칙 미발동
    q = _q(
        "imp-2",
        "기계장치를 1,000,000원에 취득, 내용연수 5년, 정액법. 재평가모형 적용, "
        "회수가능액 측정으로 손상차손을 인식한다. 손상차손은?",
        ["100,000원", "200,000원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "accounting_impairment_loss"


def test_transaction_price_allocation():
    q = _q(
        "tpa-1",
        "㈜한국은 단일 계약으로 제품 A와 1년간 유지보수 서비스를 고객에게 5,000,000원에 "
        "판매했다. 개별 판매가격은 제품 A 4,000,000원, 유지보수 서비스 2,000,000원이다. "
        "제품 A는 인도 시점에 통제가 이전된다. 인도 시점에 즉시 인식할 수익은?",
        ["3,000,000원", "3,333,333원", "4,000,000원", "5,000,000원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "accounting_transaction_price_allocation"
    assert res.chosen_index == 1  # 5,000,000 × 4,000,000/6,000,000 = 3,333,333


def test_indirect_cash_flow():
    q = _q(
        "cf-1",
        "㈜한국의 20X1년 자료가 다음과 같을 때 간접법으로 산출한 영업활동 현금흐름은? "
        "당기순이익 500,000원, 감가상각비 120,000원, 유형자산처분이익 30,000원, "
        "매출채권 증가 50,000원, 매입채무 증가 40,000원",
        ["550,000원", "580,000원", "620,000원", "740,000원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "accounting_indirect_cash_flow"
    assert res.chosen_index == 1  # 500,000+120,000−30,000−50,000+40,000 = 580,000


def test_indirect_cash_flow_abstains_on_unknown_item():
    # 부호 분류 불가 항목 포함 시 기권 (오답 방지)
    q = _q(
        "cf-2",
        "간접법 영업활동 현금흐름. 당기순이익 500,000원, 기타조정항목 99,999원.",
        ["500,000원", "599,999원"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "accounting_indirect_cash_flow"


def test_treasury_reissue_entry():
    q = _q(
        "tr-1",
        "㈜한국이 자기주식 100주를 주당 5,000원에 취득한 후, 60주를 주당 7,000원에 "
        "재발행했다. 자기주식 재발행으로 인식할 회계처리로 옳은 것은?",
        [
            "현금 420,000원 / 자기주식 300,000원, 자기주식처분이익(자본잉여금) 120,000원",
            "현금 420,000원 / 자기주식 420,000원",
            "현금 420,000원 / 자기주식 300,000원, 자기주식처분이익(당기손익) 120,000원",
            "현금 420,000원 / 자기주식 420,000원, 자본잉여금 차변 120,000원",
        ],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "accounting_treasury_reissue_entry"
    assert res.chosen_index == 0  # 현금 420,000 / 자기주식 300,000, 처분이익(자본잉여금) 120,000


def test_treasury_multi_transaction():
    q = _q(
        "tm-1",
        "(주)한국의 자기주식(200주, 취득원가 @₩7,000). 20x6년 중 (1) 자기주식 100주를 "
        "주당 ₩9,000에 처분, (2) 자기주식 50주를 주당 ₩6,000에 처분, (3) 잔여 50주를 "
        "소각하였다. 자본총계 순영향과 자기주식처분이익(손실) 잔액은? "
        "(단, 처분 전 자기주식처분이익 잔액은 없다고 가정한다.)",
        [
            "자본총계 증가 ₩1,200,000, 자기주식처분이익 ₩150,000",
            "자본총계 증가 ₩900,000, 자기주식처분이익 ₩150,000",
            "자본총계 증가 ₩1,200,000, 자기주식처분이익 ₩200,000",
            "자본총계 증가 ₩1,550,000, 자기주식처분손실 ₩50,000",
            "자본총계 증가 ₩900,000, 자기주식처분손실 ₩50,000",
        ],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "accounting_treasury_multi_transaction"
    assert res.chosen_index == 0  # 처분현금 900,000+300,000=1,200,000, 손익 200,000−50,000=150,000


def test_entertainment_expense_limit():
    q = {
        "question_id": "ent-1",
        "subject": "tax",
        "unit": "corporate_tax",
        "stem": (
            "일반법인 ㈜을의 기업업무추진비 자료이다.\n"
            "(1) 손익계산서상 계상된 기업업무추진비: 80,000,000원(전액 적격증빙 수취)\n"
            "(2) 매출액(특수관계인 매출 없음): 20,000,000,000원\n"
            "(3) 적용률: 100억원 이하 0.3%, 100억원 초과 500억원 이하 0.2%, 500억원 초과 0.03%\n"
            "(4) 일반법인 기본한도: 12,000,000원\n"
            "기업업무추진비 한도초과액으로 손금불산입할 금액은?"
        ),
        "choices": ["8,000,000원", "18,000,000원", "20,000,000원", "30,000,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "tax_entertainment_expense_limit"
    assert res.chosen_index == 1  # 80,000,000 − (12,000,000 + 50,000,000) = 18,000,000


def test_entertainment_skips_nonstandard_rate():
    # 표준 적용률 스케줄(0.3%/0.2%)이 없으면 규칙 미발동(오답 방지)
    q = {
        "question_id": "ent-2",
        "subject": "tax",
        "unit": "corporate_tax",
        "stem": (
            "기업업무추진비 한도초과액을 구하라. 계상된 기업업무추진비 80,000,000원, "
            "매출액 5,000,000,000원, 기본한도 12,000,000원이다."
        ),
        "choices": ["8,000,000원", "18,000,000원", "53,000,000원", "30,000,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "tax_entertainment_expense_limit"


def test_taxable_income_adjustment():
    q = {
        "question_id": "ti-1",
        "subject": "tax",
        "unit": "corporate_tax",
        "stem": (
            "결산서상 당기순이익은 200,000,000원이며, 다음 세무조정 사항이 확인된다.\n"
            "(1) 법인세비용 30,000,000원이 손익계산서에 계상되어 있다.\n"
            "(2) 접대비(기업업무추진비) 한도초과액 5,000,000원\n"
            "(3) 감가상각비 한도초과액 3,000,000원\n"
            "(4) 전기 감가상각비 한도초과액 중 당기 손금추인액 1,000,000원\n"
            "(5) 자기주식처분이익 4,000,000원이 자본잉여금으로 계상되어 있다.\n"
            "각 사업연도 소득금액은 얼마인가?"
        ),
        "choices": ["239,000,000원", "240,000,000원", "241,000,000원", "245,000,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "tax_taxable_income_adjustment"
    assert res.chosen_index == 2  # 200,000,000 + 42,000,000 − 1,000,000 = 241,000,000


def test_taxable_income_skips_donation():
    # 기부금 시부인 다단계 문항은 미발동(별도 한도계산 필요 → 오답 방지)
    q = {
        "question_id": "ti-2",
        "subject": "tax",
        "unit": "corporate_tax",
        "stem": (
            "기부금 반영 전 차가감소득금액 250,000,000원, 당기순이익 기준 자료.\n"
            "특례기부금 30,000,000원, 일반기부금 40,000,000원, 비지정기부금 10,000,000원.\n"
            "각 사업연도 소득금액을 계산하면?"
        ),
        "choices": ["250,000,000원", "260,000,000원", "270,000,000원", "275,000,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "tax_taxable_income_adjustment"


def test_vat_output_deemed_supply():
    q = {
        "question_id": "vat-out-1",
        "subject": "tax",
        "unit": "vat",
        "stem": (
            "부가가치세 매출세액은 얼마인가? 세율은 10%이다.\n"
            "(1) 국내거래처에 제품 판매: 200,000,000원\n"
            "(2) 미국 거래처에 직수출(선적일 기준): 100,000,000원\n"
            "(3) 거래처에 무상으로 제공한 견본품(시가): 5,000,000원\n"
            "(4) 사용인에게 작업복으로 제공: 3,000,000원\n"
            "(5) 거래처 접대 목적으로 제공한 제품(시가 8,000,000원, 원가 5,000,000원)"
        ),
        "choices": ["20,000,000원", "20,800,000원", "21,100,000원", "30,800,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "tax_vat_output_deemed_supply"
    assert res.chosen_index == 1  # 200,000,000×10% + 8,000,000×10% = 20,800,000


def test_vat_output_skips_payable_variant():
    q = {
        "question_id": "vat-out-2",
        "subject": "tax",
        "unit": "vat",
        "stem": "매출세액을 구한 뒤 납부세액을 구하라. 국내매출: 100,000,000원",
        "choices": ["5,000,000원", "10,000,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "tax_vat_output_deemed_supply"


def test_vat_payable():
    q = {
        "question_id": "vat-pay-1",
        "subject": "tax",
        "unit": "vat",
        "stem": (
            "납부세액은 얼마인가?\n"
            "(1) 국내 제품 매출액: 500,000,000원\n"
            "(2) 직수출액(선적일 기준): 200,000,000원\n"
            "(3) 대손이 확정된 외상매출금(부가가치세 포함 금액): 22,000,000원\n"
            "(4) 원재료 매입액(전액 과세사업 관련): 300,000,000원\n"
            "(5) 비영업용 소형승용차(2,000cc) 구입액: 30,000,000원\n"
            "(6) 거래처 접대 목적 선물 구입액: 10,000,000원\n"
            "(7) 공장 운영용 소모품 매입액: 20,000,000원"
        ),
        "choices": ["14,000,000원", "15,000,000원", "16,000,000원", "18,000,000원", "20,000,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "tax_vat_payable"
    assert res.chosen_index == 2  # 50,000,000 - 2,000,000 - 32,000,000 = 16,000,000


def test_vat_common_input_apportionment():
    q = {
        "question_id": "vat-common-1",
        "subject": "tax",
        "unit": "vat",
        "stem": (
            "겸영 일반과세자의 제2기 확정신고 자료이다.\n"
            "(1) 공급가액\n"
            "- 과세사업 공급가액: 예정신고기간 200,000,000원, 확정신고기간 300,000,000원\n"
            "- 면세사업 공급가액: 예정신고기간 100,000,000원, 확정신고기간 200,000,000원\n"
            "(2) 공통으로 사용하기 위해 건물을 800,000,000원(부가가치세 별도)에 취득하고 세금계산서를 수취하였다.\n"
            "(3) 공통으로 사용할 기계장치를 80,000,000원(부가가치세 별도)에 취득하였다.\n"
            "(4) 위 자산 외 확정신고기간의 매입세액(공통매입세액 제외)은 모두 과세사업 관련이며 30,000,000원이다.\n"
            "공제받을 수 있는 매입세액은 얼마인가?"
        ),
        "choices": ["75,000,000원", "78,000,000원", "80,000,000원", "85,000,000원", "88,000,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "tax_vat_common_input_apportionment"
    assert res.chosen_index == 3  # (80,000,000+8,000,000)*0.625 + 30,000,000 = 85,000,000


def test_financial_income_grossup_interest_fills_cap():
    # 이자 10,000,000 + 배당 20,000,000 = 30,000,000(>2천만), 직장공제회 분리과세 제외
    # Gross-up대상 = 20,000,000 − (20,000,000 − 10,000,000) = 10,000,000 → 합산 31,000,000
    q = {
        "question_id": "fg-1",
        "subject": "tax",
        "unit": "income_tax",
        "stem": (
            "거주자 김씨의 종합소득금액 계산 시 합산되는 금융소득금액(배당가산액 포함)은 "
            "얼마인가? (단, 배당가산율은 10%를 적용한다)\n"
            "(1) 국내 비상장법인 현금배당: 12,000,000원\n"
            "(2) 국내 상장법인 현금배당: 8,000,000원\n"
            "(3) 직장공제회 초과반환금: 5,000,000원\n"
            "(4) 비영업대금의 이익: 6,000,000원\n"
            "(5) 국내은행 정기예금이자: 4,000,000원"
        ),
        "choices": [
            "30,000,000원",
            "31,000,000원",
            "31,100,000원",
            "32,000,000원",
            "35,000,000원",
        ],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "tax_financial_income_grossup"
    assert res.chosen_index == 1  # 31,000,000원


def test_financial_income_grossup_skips_business_expense():
    # 사업소득 필요경비형: '금융소득'/'가산'/'Gross-up' 키워드 없음 → 본 규칙 미발동(오답 방지)
    q = {
        "question_id": "fg-2",
        "subject": "tax",
        "unit": "income_tax",
        "stem": (
            "거주자 을(복식부기의무자)의 사업소득금액 계산 시 필요경비에 산입할 수 있는 "
            "금액의 합계는? (1) 본인에 대한 급여: 50,000,000원 (2) 접대비: 8,000,000원 "
            "(3) 가사 관련 경비: 3,000,000원 (4) 감가상각비: 12,000,000원 "
            "(5) 본인 국민건강보험료: 2,400,000원"
        ),
        "choices": ["20,000,000원", "22,400,000원", "70,000,000원", "72,400,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "tax_financial_income_grossup"


def test_acquisition_tax_base():
    q = {
        "question_id": "acq-1",
        "subject": "tax",
        "unit": "local_tax_etc",
        "stem": (
            "갑은 상가건물을 유상승계취득하였다. 갑이 부담할 취득세 본세(농어촌특별세 및 "
            "지방교육세 제외) 산출세액은 얼마인가?\n"
            "(1) 취득가액(사실상의 취득가격): 1,200,000,000원\n"
            "(2) 취득에 직접 소요된 중개수수료: 10,000,000원 (취득가격에 포함되지 않은 금액)\n"
            "(3) 취득세 표준세율: 주택 외 유상승계취득 4%\n"
            "(4) 취득시기 이후 지출한 자본적 지출액: 20,000,000원"
        ),
        "choices": [
            "48,000,000원",
            "48,400,000원",
            "48,800,000원",
            "49,200,000원",
            "49,600,000원",
        ],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "tax_acquisition_base_rate"
    assert res.chosen_index == 1  # 1,210,000,000 × 4% = 48,400,000


def test_acquisition_tax_base_skips_combined():
    # 취득세+지방교육세+농특세 합계형은 본세 단독 규칙이 발동하지 않아야 함
    q = {
        "question_id": "acq-2",
        "subject": "tax",
        "unit": "local_tax_etc",
        "stem": (
            "갑이 납부하여야 할 취득세, 지방교육세, 농어촌특별세의 합계액은 얼마인가? "
            "취득가액 1,200,000,000원, 취득세 표준세율은 4%."
        ),
        "choices": ["52,800,000원", "55,200,000원", "57,600,000원"],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "tax_acquisition_base_rate"


def test_acquisition_tax_with_surtaxes():
    q = {
        "question_id": "acqs-1",
        "subject": "tax",
        "unit": "local_tax_etc",
        "stem": (
            "갑이 납부하여야 할 취득세, 지방교육세, 농어촌특별세의 합계액은 얼마인가? "
            "(취득세 표준세율은 4%, 지방교육세는 「지방세법」 제151조 규정에 따라 산정한다.)\n"
            "• 매매대금: 1,200,000,000원\n"
            "• 농어촌특별세는 취득세 표준세율 2% 분에 해당하는 산출세액의 10%로 한다."
        ),
        "choices": [
            "52,800,000원",
            "55,200,000원",
            "57,600,000원",
            "60,000,000원",
            "62,400,000원",
        ],
    }
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "tax_acquisition_with_surtaxes"
    assert res.chosen_index == 1  # 48,000,000 + 4,800,000 + 2,400,000 = 55,200,000


def test_quantity_theory_inflation_fires():
    q = json.loads(
        pathlib.Path(
            "data/seeds/evaluation/cpa1-eval-economics-014.evaluation_question.json"
        ).read_text()
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "economics_quantity_theory_inflation"
    assert res.chosen_index == 1  # '3%'
    assert q["choices"][res.chosen_index] == q["correct_answer"]


def test_quantity_theory_does_not_fire_on_uip():
    q = json.loads(
        pathlib.Path(
            "data/seeds/evaluation/cpa1-eval-economics-015.evaluation_question.json"
        ).read_text()
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "economics_quantity_theory_inflation"


def test_uip_return_gap_fires():
    q = json.loads(
        pathlib.Path(
            "data/seeds/evaluation/cpa1-eval-economics-015.evaluation_question.json"
        ).read_text()
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "economics_uip_return_gap"
    assert res.chosen_index == 1  # '1%p'
    assert q["choices"][res.chosen_index] == q["correct_answer"]


def test_uip_does_not_fire_on_eoq():
    q = json.loads(
        pathlib.Path(
            "data/seeds/evaluation/cpa1-eval-management-013.evaluation_question.json"
        ).read_text()
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "economics_uip_return_gap"


def test_eoq_fires():
    q = json.loads(
        pathlib.Path(
            "data/seeds/evaluation/cpa1-eval-management-013.evaluation_question.json"
        ).read_text()
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] == "management_eoq"
    assert res.chosen_index == 2  # '1,581개'
    assert q["choices"][res.chosen_index] == q["correct_answer"]


def test_eoq_does_not_fire_on_quantity_theory():
    q = json.loads(
        pathlib.Path(
            "data/seeds/evaluation/cpa1-eval-economics-014.evaluation_question.json"
        ).read_text()
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] != "management_eoq"
