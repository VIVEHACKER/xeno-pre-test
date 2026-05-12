from __future__ import annotations

import json
from pathlib import Path

from cpa_first.cli.validate import validate_file


ROOT = Path(__file__).resolve().parents[1]


def _write_question(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "sample.evaluation_question.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _base_question(**overrides) -> dict:
    payload = {
        "question_id": "sample",
        "exam": "CPA_1",
        "subject": "tax",
        "unit": "corporate_tax",
        "stem": "샘플 문항",
        "choices": ["100원", "200원", "300원", "400원"],
        "correct_choice": 1,
        "correct_answer": "200원",
        "explanation": "정답은 200원이다.",
        "rights_status": "synthetic_seed",
        "review_status": "ai_draft_verified",
    }
    payload.update(overrides)
    return payload


def test_evaluation_question_requires_correct_answer(tmp_path: Path):
    payload = _base_question()
    payload.pop("correct_answer")

    errors = validate_file(_write_question(tmp_path, payload), "evaluation_question")

    assert any("correct_answer" in error for error in errors)


def test_evaluation_question_rejects_correct_answer_mismatch(tmp_path: Path):
    payload = _base_question(correct_answer="300원")

    errors = validate_file(_write_question(tmp_path, payload), "evaluation_question")

    assert any("correct_answer must equal choices[correct_choice]" in error for error in errors)


def test_evaluation_question_rejects_explanation_claiming_other_choice_is_answer(tmp_path: Path):
    payload = _base_question(
        explanation="과세표준을 계산하면 300원이다. ③ 300원이 정답이다."
    )

    errors = validate_file(_write_question(tmp_path, payload), "evaluation_question")

    assert any("explanation marks a non-correct choice as 정답" in error for error in errors)


def test_evaluation_question_rejects_choice_correction_note(tmp_path: Path):
    payload = _base_question(
        explanation="정확 계산은 500원이다. 보기 중 가장 근접한 값을 고른다. 보기 보정 권장."
    )

    errors = validate_file(_write_question(tmp_path, payload), "evaluation_question")

    assert any("보기 보정 권장" in error for error in errors)


def test_real_evaluation_seeds_have_explicit_matching_correct_answer():
    errors: list[str] = []
    for path in sorted((ROOT / "data" / "seeds" / "evaluation").glob("*.evaluation_question.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        correct_choice = data.get("correct_choice")
        choices = data.get("choices", [])
        if not isinstance(correct_choice, int) or not (0 <= correct_choice < len(choices)):
            errors.append(f"{path.name}: correct_choice out of range")
            continue
        if data.get("correct_answer") != choices[correct_choice]:
            errors.append(
                f"{path.name}: correct_answer={data.get('correct_answer')!r} "
                f"expected={choices[correct_choice]!r}"
            )

    assert errors == []
