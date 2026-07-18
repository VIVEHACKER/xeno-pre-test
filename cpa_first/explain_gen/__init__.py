"""실기출 해설 생성 파이프라인 — blind solve → 정답키 대조 검증 → 저장.

eval_gen(변형문제 생성)과 대칭 구조. 핵심 불변량:
- solver에는 정답키가 절대 전달되지 않는다 (SOLVER_INPUT_FIELDS 화이트리스트).
- 정답키 대조는 solve가 끝난 뒤에만 수행한다.
- 검증 통과(STATUS_VERIFIED) 해설만 학습자 노출 대상이 된다.
"""

from cpa_first.explain_gen.generator import (
    SOLVER_INPUT_FIELDS,
    build_blind_question,
    generate_explanation,
    run_batch,
)
from cpa_first.explain_gen.tutorial_judge import (
    judge_tutorial,
    run_tutorial_judge_batch,
    summarize_tutorial_judgments,
)

__all__ = [
    "SOLVER_INPUT_FIELDS",
    "build_blind_question",
    "generate_explanation",
    "run_batch",
    "judge_tutorial",
    "run_tutorial_judge_batch",
    "summarize_tutorial_judgments",
]
