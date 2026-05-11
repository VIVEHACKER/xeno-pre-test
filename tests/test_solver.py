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
