"""eval_gen — CPA 1차 평가셋 자동 생성 + 검증.

GREEN 단계: 테스트가 통과하는 최소 구현.
"""

from cpa_first.eval_gen.generator import BatchSpec, generate_batch
from cpa_first.eval_gen.validator import ValidationResult, validate_question
from cpa_first.eval_gen.writer import next_question_id, write_question

__all__ = [
    "BatchSpec",
    "ValidationResult",
    "generate_batch",
    "next_question_id",
    "validate_question",
    "write_question",
]
