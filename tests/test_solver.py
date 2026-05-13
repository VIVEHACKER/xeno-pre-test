"""Solver + Tool 단위 테스트.

mock / stub 모드만 검증. live 모드는 ANTHROPIC_API_KEY가 필요하고
실비용이 들어 별도 통합 환경에서 수동 실행.
"""

from __future__ import annotations

import pytest

from cpa_first.solver import (
    Solver,
    amortization_table,
    calculator,
    create_solver,
    date_diff,
)
from cpa_first.solver.solver import (
    _extract_answer_index,
    load_evaluation_questions,
)


QUESTION = {
    "question_id": "test-001",
    "exam": "CPA_1",
    "subject": "accounting",
    "unit": "test_unit",
    "stem": "1+1은?",
    "choices": ["1", "2", "3", "4"],
    "correct_choice": 1,
    "rights_status": "synthetic_seed",
    "review_status": "expert_reviewed",
}


# ----- tools -----


def test_calculator_basic():
    assert calculator({"op": "add", "operands": [1, 2, 3]})["result"] == 6
    assert calculator({"op": "mul", "operands": [2, 3, 4]})["result"] == 24
    assert calculator({"op": "div", "operands": [10, 2]})["result"] == 5


def test_calculator_pow_avg():
    assert calculator({"op": "pow", "operands": [2, 10]})["result"] == 1024
    assert calculator({"op": "avg", "operands": [2, 4, 6]})["result"] == 4


def test_calculator_div_zero():
    with pytest.raises(ValueError):
        calculator({"op": "div", "operands": [1, 0]})


def test_calculator_rejects_unknown_op():
    with pytest.raises(Exception):
        calculator({"op": "sqrt", "operands": [4]})


def test_amortization_table_matches_effective_interest_example():
    """평가 시드 cpa1-eval-accounting-001의 1기 이자수익 계산."""
    result = amortization_table(
        {
            "face_value": 1000000,
            "coupon_rate": 0.08,
            "effective_rate": 0.10,
            "periods": 3,
            "initial_book_value": 950260,
        }
    )
    first = result["rows"][0]
    assert first["interest_revenue"] == pytest.approx(95026.0, abs=0.01)
    assert first["cash_interest"] == 80000.0
    # 3기 누적 후 장부금액이 액면금액에 충분히 근접해야 함
    assert abs(result["final_book_value"] - 1000000) < 200


def test_date_diff_units():
    assert date_diff({"start": "2026-01-01", "end": "2026-01-11", "unit": "days"})["result"] == 10
    months = date_diff({"start": "2026-01-15", "end": "2026-05-14", "unit": "months"})["result"]
    assert months == 3  # 5/14는 1/15보다 day가 작으므로 4개월에서 -1
    years = date_diff({"start": "2024-02-29", "end": "2026-02-28", "unit": "years"})["result"]
    assert years == 1  # 2/28은 2/29보다 작아 -1


def test_date_diff_end_before_start_rejected():
    with pytest.raises(ValueError):
        date_diff({"start": "2026-05-01", "end": "2026-04-01"})


# ----- solver mock/stub -----


def test_mock_solver_is_deterministic():
    solver = create_solver(mode="mock")
    a = solver.solve(QUESTION)
    b = solver.solve(QUESTION)
    assert a.chosen_index == b.chosen_index
    assert a.mode == "mock"


def test_mock_solver_within_choice_range():
    solver = create_solver(mode="mock")
    for i in range(20):
        q = dict(QUESTION, question_id=f"q-{i}")
        result = solver.solve(q)
        assert 0 <= result.chosen_index < len(q["choices"])


def test_create_solver_defaults_to_reasoned():
    solver = create_solver()

    assert solver.mode == "reasoned"


def test_reasoned_solver_solves_npv_without_answer_key_leakage():
    question = {
        **QUESTION,
        "question_id": "reasoned-npv",
        "subject": "business",
        "unit": "financial_management",
        "stem": (
            "투자안 A는 오늘 1,000,000원을 투자하면 1년 뒤 500,000원, "
            "2년 뒤 700,000원의 현금흐름을 제공한다. 할인율이 연 10%일 때 "
            "투자안 A의 순현재가치(NPV)는 얼마인가? (원 단위 미만 절사)"
        ),
        "choices": ["200,000원", "1,033,057원", "33,057원", "1,200,000원"],
        "correct_choice": 0,
        "correct_answer": "200,000원",
    }

    result = Solver(mode="reasoned").solve(question)

    assert result.chosen_index == 2
    assert result.mode == "reasoned"
    assert "문항 신호" in result.rationale
    assert "떠올려야 할 주제" in result.rationale
    assert "풀이식" in result.rationale
    assert "오답 제거" in result.rationale
    assert "ANSWER: 2" in result.rationale


def test_reasoned_solver_solves_moving_average_inventory():
    question = {
        **QUESTION,
        "question_id": "reasoned-moving-average",
        "subject": "accounting",
        "unit": "inventory",
        "stem": (
            "㈜CF의 20X1년 재고자산 자료는 다음과 같다. 기초재고 100개(@1,000), "
            "1차 매입 200개(@1,200), 2차 매입 100개(@1,400), 기말재고 수량 150개. "
            "회사가 이동평균법을 사용하고 있고 1차 매입 후 250개를 판매한 다음 "
            "2차 매입이 이루어졌다면, 기말재고 금액은 얼마인가?"
        ),
        "choices": ["180,000원", "190,000원", "196,667원", "210,000원"],
    }

    result = Solver(mode="reasoned").solve(question)

    assert result.chosen_index == 2
    assert "이동평균법" in result.rationale
    assert "196,667" in result.rationale


def test_reasoned_solver_solves_corporate_tax_progressive_rate():
    question = {
        **QUESTION,
        "question_id": "reasoned-corporate-tax",
        "subject": "tax",
        "unit": "corporate_tax",
        "stem": (
            "㈜한강의 다음 자료를 이용하여 산출세액을 계산하면? "
            "각사업연도소득금액 350,000,000원, 비과세소득 10,000,000원, "
            "이월결손금(2020년 발생, 일반결손금) 45,000,000원, 소득공제 5,000,000원이 있다. "
            "2026년 법인세율은 과세표준 2억원 이하 9%, "
            "2억원 초과 200억원 이하 19%, 200억원 초과 3,000억원 이하 21%, "
            "3,000억원 초과 24%이다."
        ),
        "choices": [
            "33,650,000원",
            "34,150,000원",
            "35,100,000원",
            "36,100,000원",
            "37,050,000원",
        ],
    }

    result = Solver(mode="reasoned").solve(question)

    assert result.chosen_index == 2
    assert "과세표준" in result.rationale
    assert "35,100,000" in result.rationale


def test_reasoned_solver_uses_known_solution_bank_for_unsupported_concepts():
    question = {
        **QUESTION,
        "question_id": "reasoned-known-law",
        "subject": "tax",
        "unit": "local_tax_etc",
        "stem": "지방세기본법상 부과제척기간에 관한 설명으로 옳지 않은 것은?",
        "choices": [
            "사기나 부정행위가 있으면 10년이다.",
            "무신고의 경우 7년이다.",
            "일반적인 경우 부과제척기간은 7년이다.",
            "기간이 끝난 날 후에는 부과할 수 없는 것이 원칙이다.",
        ],
        "correct_choice": 2,
        "correct_answer": "일반적인 경우 부과제척기간은 7년이다.",
        "concept_tags": ["지방세기본법", "부과제척기간"],
        "explanation": "일반적인 경우 지방세 부과제척기간은 5년이므로 7년이라는 설명이 옳지 않다.",
        "review_status": "ai_draft_verified",
    }

    result = Solver(mode="reasoned").solve(question)

    assert result.chosen_index == 2
    assert "known_solution_bank" in result.rationale
    assert "검수 풀이 데이터" in result.rationale
    assert "ANSWER: 2" in result.rationale


def test_stub_solver_always_picks_first():
    solver = Solver(mode="stub")
    result = solver.solve(QUESTION)
    assert result.chosen_index == 0
    assert result.mode == "stub"


def test_solver_unknown_mode_raises():
    solver = Solver(mode="nonsense")
    with pytest.raises(ValueError):
        solver.solve(QUESTION)


# ----- live invoke 주입 (Anthropic 미설치 환경 OK) -----


def test_live_invoke_injection_parses_answer():
    """invoke 함수를 직접 주입해 Anthropic 없이 live 경로를 단위 테스트."""
    fake_invoke = lambda system, user: "1회전: 식. 2회전: 검산.\nANSWER: 2"
    solver = Solver(mode="live", invoke=fake_invoke)
    result = solver.solve(QUESTION)
    assert result.chosen_index == 2
    assert result.mode == "live"


def test_live_invoke_missing_answer_returns_neg_one():
    fake_invoke = lambda system, user: "근거가 부족합니다."
    solver = Solver(mode="live", invoke=fake_invoke)
    result = solver.solve(QUESTION)
    assert result.chosen_index == -1


def test_live_invoke_out_of_range_returns_neg_one():
    fake_invoke = lambda system, user: "ANSWER: 99"
    solver = Solver(mode="live", invoke=fake_invoke)
    result = solver.solve(QUESTION)
    assert result.chosen_index == -1


def test_extract_answer_index_variants():
    assert _extract_answer_index("ANSWER: 1", 4) == 1
    assert _extract_answer_index("answer:  3 ", 4) == 3
    assert _extract_answer_index("정답은 2번", 4) == -1
    assert _extract_answer_index("ANSWER: 4", 4) == -1


# ----- 평가 시드 로드 -----


def test_load_evaluation_questions_smoke(tmp_path):
    sample = {
        "question_id": "smoke-1",
        "exam": "CPA_1",
        "subject": "accounting",
        "unit": "test",
        "stem": "test",
        "choices": ["a", "b", "c", "d"],
        "correct_choice": 0,
        "rights_status": "synthetic_seed",
        "review_status": "expert_reviewed",
    }
    import json

    target = tmp_path / "smoke.evaluation_question.json"
    with target.open("w", encoding="utf-8") as f:
        json.dump(sample, f, ensure_ascii=False)
    loaded = load_evaluation_questions(tmp_path)
    assert len(loaded) == 1
    assert loaded[0]["question_id"] == "smoke-1"
