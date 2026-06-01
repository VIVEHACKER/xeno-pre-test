"""결정론 reasoned solver 신규 규칙 단위 테스트 (정액법 감가상각, 손익분기점 매출액)."""

from __future__ import annotations

from cpa_first.solver.reasoned import solve_reasoned


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


def test_rule_does_not_misfire_on_unrelated():
    # 정액법/손익분기점 신호 없는 문항엔 신규 규칙이 발동하지 않음
    q = _q(
        "u-1",
        "다음 중 무형자산으로 분류할 수 없는 것은?",
        ["영업권", "특허권", "재고자산", "상표권"],
    )
    res = solve_reasoned(q)
    assert res.tool_calls[0]["rule_id"] not in {
        "accounting_straight_line_depreciation",
        "cost_bep_sales",
    }
