"""Solver가 사용하는 도구.

LLM이 임의 코드 실행하지 않도록 Pydantic 검증된 입력만 받는다.
회계학 계산형에 필요한 최소 도구 4종으로 시작.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


# ----- calculator -----


class CalculatorInput(BaseModel):
    op: str = Field(pattern="^(add|sub|mul|div|pow|sum|avg)$")
    operands: list[float] = Field(min_length=1)


def calculator(payload: dict[str, Any]) -> dict[str, Any]:
    args = CalculatorInput.model_validate(payload)
    nums = args.operands
    op = args.op

    if op == "add":
        result = sum(nums)
    elif op == "sub":
        result = nums[0] - sum(nums[1:])
    elif op == "mul":
        result = 1.0
        for n in nums:
            result *= n
    elif op == "div":
        if any(n == 0 for n in nums[1:]):
            raise ValueError("division by zero")
        result = nums[0]
        for n in nums[1:]:
            result /= n
    elif op == "pow":
        if len(nums) != 2:
            raise ValueError("pow requires exactly 2 operands")
        result = nums[0] ** nums[1]
    elif op == "sum":
        result = sum(nums)
    elif op == "avg":
        result = sum(nums) / len(nums)
    else:
        raise ValueError(f"unknown op: {op}")

    return {"op": op, "result": result}


# ----- amortization_table -----


class AmortizationInput(BaseModel):
    face_value: float = Field(gt=0)
    coupon_rate: float = Field(ge=0, le=1)
    effective_rate: float = Field(ge=0, le=1)
    periods: int = Field(ge=1, le=40)
    initial_book_value: float = Field(gt=0)


def amortization_table(payload: dict[str, Any]) -> dict[str, Any]:
    """유효이자율법 매기 누적 표.

    각 기 (이자수익, 현금수취, 할인/할증차금 상각, 기말 장부금액)을 산출.
    """
    args = AmortizationInput.model_validate(payload)
    rows: list[dict[str, float]] = []
    book_value = args.initial_book_value
    for period in range(1, args.periods + 1):
        interest_revenue = round(book_value * args.effective_rate, 4)
        cash_interest = round(args.face_value * args.coupon_rate, 4)
        amortization = round(interest_revenue - cash_interest, 4)
        book_value = round(book_value + amortization, 4)
        rows.append(
            {
                "period": period,
                "interest_revenue": interest_revenue,
                "cash_interest": cash_interest,
                "amortization": amortization,
                "ending_book_value": book_value,
            }
        )
    return {"rows": rows, "final_book_value": book_value}


# ----- date_diff -----


class DateDiffInput(BaseModel):
    start: str  # YYYY-MM-DD
    end: str
    unit: str = Field(pattern="^(days|months|years)$", default="days")


def date_diff(payload: dict[str, Any]) -> dict[str, Any]:
    args = DateDiffInput.model_validate(payload)
    start = _parse_date(args.start)
    end = _parse_date(args.end)
    if end < start:
        raise ValueError("end before start")

    delta_days = (end - start).days
    if args.unit == "days":
        result: float = delta_days
    elif args.unit == "months":
        result = (end.year - start.year) * 12 + (end.month - start.month)
        if end.day < start.day:
            result -= 1
    else:  # years
        result = end.year - start.year
        if (end.month, end.day) < (start.month, start.day):
            result -= 1

    return {"start": args.start, "end": args.end, "unit": args.unit, "result": result, "days": delta_days}


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


# ----- 디스패치 (LLM이 이름으로 호출) -----

TOOL_REGISTRY: dict[str, Any] = {
    "calculator": calculator,
    "amortization_table": amortization_table,
    "date_diff": date_diff,
}


def run_tool(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOL_REGISTRY:
        raise ValueError(f"unknown tool: {name}")
    return TOOL_REGISTRY[name](payload)
