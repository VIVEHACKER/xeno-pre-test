"""AI 응시자 모듈. 모의 평가 문제를 두-pass 추론으로 풀이.

reasoned 모드: API 없이 문항 신호, 개념, 풀이식, 오답 제거를 거쳐 답을 고르는 기본 경로.
mock 모드: 결정론적 해시 답. 테스트/CI 비교용.
live 모드: Anthropic Claude API 호출. ANTHROPIC_API_KEY 필요.

환경변수 CPA_SOLVER_MODE=live 또는 인자로 mode='live' 지정.
"""

from cpa_first.solver.tools import (
    amortization_table,
    calculator,
    date_diff,
)
from cpa_first.solver.solver import (
    SolveResult,
    Solver,
    create_solver,
    load_evaluation_questions,
)

__all__ = [
    "Solver",
    "SolveResult",
    "create_solver",
    "load_evaluation_questions",
    "calculator",
    "amortization_table",
    "date_diff",
]
