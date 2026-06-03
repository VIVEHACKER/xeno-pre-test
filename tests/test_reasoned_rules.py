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
