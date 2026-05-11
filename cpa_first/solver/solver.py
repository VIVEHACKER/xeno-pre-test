"""Solver 본체. mock / live 모드 분기.

mock 모드는 입력 question_id 해시 기반 결정론 stub. 실제 LLM 호출 없이
벤치마크 파이프라인이 동작하는지 검증할 때 사용.

live 모드는 Anthropic Claude API 호출. system 프롬프트 + two-pass
지시 + 출력 포맷 강제. ANTHROPIC_API_KEY 필요.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable


DEFAULT_MODEL = "claude-opus-4-7"


@dataclass
class SolveResult:
    question_id: str
    chosen_index: int
    rationale: str
    mode: str
    model: str | None = None
    raw_response: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Solver:
    mode: str = "mock"
    model: str = DEFAULT_MODEL
    client: Any = None  # live 모드에서 anthropic.Anthropic 인스턴스
    invoke: Callable[[str, str], str] | None = None  # 테스트용 주입 가능

    def solve(self, question: dict[str, Any]) -> SolveResult:
        if self.mode == "mock":
            return _solve_mock(question)
        if self.mode == "live":
            return _solve_live(question, self)
        if self.mode == "stub":
            # 결정론적 첫 보기. mock보다 단순.
            return SolveResult(
                question_id=question["question_id"],
                chosen_index=0,
                rationale="stub: 항상 첫 보기.",
                mode="stub",
            )
        raise ValueError(f"unknown solver mode: {self.mode}")


def create_solver(mode: str | None = None, **kwargs: Any) -> Solver:
    resolved_mode = mode or os.environ.get("CPA_SOLVER_MODE", "mock")
    if resolved_mode == "live":
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "live 모드는 anthropic 패키지가 필요합니다: pip install anthropic"
            ) from exc
        client = anthropic.Anthropic()
        return Solver(mode="live", model=kwargs.get("model", DEFAULT_MODEL), client=client)
    return Solver(mode=resolved_mode, **kwargs)


# ----- mock -----


def _solve_mock(question: dict[str, Any]) -> SolveResult:
    """결정론적 해시 기반 선택. question_id가 같으면 항상 같은 답.

    실제 합격선과 무관하지만 파이프라인 검증과 결정론 테스트에 충분.
    """
    digest = hashlib.sha256(question["question_id"].encode("utf-8")).digest()
    chosen = digest[0] % len(question["choices"])
    return SolveResult(
        question_id=question["question_id"],
        chosen_index=chosen,
        rationale=(
            f"[MOCK] question_id 해시 기반 선택. 실제 추론 없음. "
            f"운영에서는 CPA_SOLVER_MODE=live 로 전환."
        ),
        mode="mock",
    )


# ----- live -----


SYSTEM_PROMPT = """당신은 한국 공인회계사 1차 시험(회계학·세법개론) 응시자입니다.
출력 규칙:
- 정답은 보기 인덱스(0-기반)로 한 줄에 "ANSWER: <index>" 형식으로 표시한다.
- 그 위에 풀이 근거를 5~10줄로 압축한다.
- 추측 답변 금지. 근거가 부족하면 "INSUFFICIENT EVIDENCE"라고 명시한 뒤 가장 가능성 높은 보기를 ANSWER로 표시한다.
- 회계기준·세법 조문 인용 시 가능한 한 근거 위치(예: K-IFRS 1109호, 법인세법 시행령 제19조)를 함께 표시한다.

추론 절차 (반드시 따른다):
1) 1회전: 문제 조건을 추출하고 식 또는 분류 기준을 잡는다. 답을 내지 않는다.
2) 2회전: 조건 누락·계산 실수·매력적 오답을 점검한 뒤 답을 확정한다.

세법은 적용연도를 반드시 확인한다. 회계는 K-IFRS 기준이다."""


USER_TEMPLATE = """과목: {subject}
단원: {unit}
{year_line}

[문제]
{stem}

[보기]
{choices_block}

위 절차에 따라 풀이하고 ANSWER 줄을 마지막에 둔다."""


def _solve_live(question: dict[str, Any], solver: Solver) -> SolveResult:
    choices_block = "\n".join(
        f"{i}. {choice}" for i, choice in enumerate(question["choices"])
    )
    year = question.get("applicable_year")
    year_line = f"적용연도: {year}" if year else "적용연도: 미지정"

    user_message = USER_TEMPLATE.format(
        subject=question["subject"],
        unit=question["unit"],
        year_line=year_line,
        stem=question["stem"],
        choices_block=choices_block,
    )

    if solver.invoke is not None:
        raw = solver.invoke(SYSTEM_PROMPT, user_message)
    else:
        raw = _call_anthropic(solver, user_message)

    chosen = _extract_answer_index(raw, len(question["choices"]))

    return SolveResult(
        question_id=question["question_id"],
        chosen_index=chosen,
        rationale=raw[-2000:],  # 너무 긴 경우 끝부분만
        mode="live",
        model=solver.model,
        raw_response=raw,
    )


def _call_anthropic(solver: Solver, user_message: str) -> str:
    """Anthropic 호출 골격. live 모드에서만 사용. 비용 관리 책임은 호출자."""
    response = solver.client.messages.create(
        model=solver.model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    parts: list[str] = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts)


_ANSWER_RE = re.compile(r"ANSWER\s*:\s*([0-9]+)", re.IGNORECASE)


def _extract_answer_index(raw: str, max_choices: int) -> int:
    """ANSWER 라인 파싱. 실패 또는 범위 초과는 -1 반환."""
    match = _ANSWER_RE.search(raw)
    if not match:
        return -1
    idx = int(match.group(1))
    if 0 <= idx < max_choices:
        return idx
    return -1


def load_evaluation_questions(directory) -> list[dict[str, Any]]:
    """평가 시드 디렉터리에서 evaluation_question JSON 로드."""
    from pathlib import Path

    base = Path(directory)
    items: list[dict[str, Any]] = []
    for path in sorted(base.glob("*.evaluation_question.json")):
        with path.open("r", encoding="utf-8") as f:
            items.append(json.load(f))
    return items
