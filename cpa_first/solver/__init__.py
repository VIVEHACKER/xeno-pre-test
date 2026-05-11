"""AI 응시자 모듈. 모의 평가 문제를 두-pass 추론으로 풀이.

mock 모드: 결정론적 stub 답(첫 보기). 테스트/CI 기본.
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
