"""eval_gen 모듈 단위 테스트.

live 모드 없이 invoke를 주입하여 결정론 테스트.
"""

from __future__ import annotations

import json

import pytest

from cpa_first.eval_gen import (
    BatchSpec,
    ValidationResult,
    generate_batch,
    next_question_id,
    validate_question,
    write_question,
)


# ----- generator -----


def _fake_batch_json(unit: str = "lease", n: int = 2) -> str:
    return json.dumps(
        {
            "questions": [
                {
                    "exam": "CPA_1",
                    "subject": "accounting",
                    "unit": unit,
                    "stem": f"문항 {i} 본문",
                    "choices": ["A", "B", "C", "D"],
                    "correct_choice": i % 4,
                    "explanation": "해설",
                    "concept_tags": ["t1"],
                    "applicable_year": 2026,
                    "expected_seconds": 90,
                    "difficulty": "hard",
                    "difficulty_score": 4,
                    "bloom_level": "analyze",
                }
                for i in range(n)
            ]
        },
        ensure_ascii=False,
    )


def test_generate_batch_parses_json():
    spec = BatchSpec(subject="accounting", unit="lease", difficulty="hard", count=2)
    invoke = lambda system, user: _fake_batch_json("lease", 2)
    result = generate_batch(spec, invoke)
    assert len(result) == 2
    assert all(q["subject"] == "accounting" for q in result)
    assert all(q["unit"] == "lease" for q in result)
    assert all(q["difficulty"] == "hard" for q in result)
    assert all(q["rights_status"] == "synthetic_seed" for q in result)
    assert all(q["review_status"] == "ai_draft" for q in result)


def test_generate_batch_retries_on_bad_json():
    calls = {"n": 0}

    def invoke(system, user):
        calls["n"] += 1
        if calls["n"] == 1:
            return "not json at all"
        return _fake_batch_json("lease", 2)

    spec = BatchSpec(subject="accounting", unit="lease", difficulty="hard", count=2)
    result = generate_batch(spec, invoke, max_retries=1)
    assert len(result) == 2
    assert calls["n"] == 2


def test_generate_batch_gives_up_after_retries():
    spec = BatchSpec(subject="accounting", unit="lease", difficulty="hard", count=2)
    invoke = lambda system, user: "garbage"
    result = generate_batch(spec, invoke, max_retries=1)
    assert result == []


def test_generate_batch_strips_extra_prose():
    """모델이 ```json 코드블록으로 감싸도 파싱 성공."""
    spec = BatchSpec(subject="tax", unit="vat", difficulty="mid", count=1)
    invoke = lambda system, user: f"여기 결과입니다:\n```json\n{_fake_batch_json('vat', 1)}\n```\n끝."
    result = generate_batch(spec, invoke)
    assert len(result) == 1


# ----- validator -----


def test_validate_approve():
    invoke = lambda system, user: json.dumps(
        {"verdict": "approve", "issues": [], "attractor_traps": ["계산 실수 유도"]}
    )
    q = {"question_id": "x", "stem": "s", "choices": ["a", "b"], "correct_choice": 0}
    r = validate_question(q, invoke)
    assert r.verdict == "approve"
    assert r.attractor_traps == ["계산 실수 유도"]
    assert r.revised is None


def test_validate_revise_uses_revised():
    revised_q = {"stem": "수정된 본문", "choices": ["a", "b", "c", "d"], "correct_choice": 1}
    invoke = lambda system, user: json.dumps(
        {
            "verdict": "revise",
            "issues": ["오답 약함"],
            "attractor_traps": [],
            "revised": revised_q,
        }
    )
    q = {"stem": "원본", "choices": ["a", "b", "c", "d"], "correct_choice": 0}
    r = validate_question(q, invoke)
    assert r.verdict == "revise"
    assert r.revised == revised_q


def test_validate_reject():
    invoke = lambda system, user: json.dumps(
        {"verdict": "reject", "issues": ["복수 정답"], "attractor_traps": []}
    )
    q = {"stem": "s"}
    r = validate_question(q, invoke)
    assert r.verdict == "reject"


def test_validate_bad_json_returns_reject():
    invoke = lambda system, user: "garbage"
    r = validate_question({"stem": "s"}, invoke)
    assert r.verdict == "reject"
    assert "parse" in r.issues[0].lower() or "json" in r.issues[0].lower()


# ----- writer -----


def test_next_question_id_continues_sequence(tmp_path):
    (tmp_path / "cpa1-eval-accounting-001.evaluation_question.json").write_text("{}")
    (tmp_path / "cpa1-eval-accounting-008.evaluation_question.json").write_text("{}")
    assert next_question_id("accounting", tmp_path) == "cpa1-eval-accounting-009"


def test_next_question_id_starts_at_001(tmp_path):
    assert next_question_id("tax", tmp_path) == "cpa1-eval-tax-001"


def test_write_question_saves_with_id(tmp_path):
    q = {
        "exam": "CPA_1",
        "subject": "accounting",
        "unit": "lease",
        "stem": "본문",
        "choices": ["a", "b", "c", "d"],
        "correct_choice": 0,
        "rights_status": "synthetic_seed",
        "review_status": "ai_draft",
    }
    path = write_question(q, tmp_path)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["question_id"] == "cpa1-eval-accounting-001"
    assert data["unit"] == "lease"


def test_write_question_does_not_overwrite(tmp_path):
    existing = tmp_path / "cpa1-eval-accounting-001.evaluation_question.json"
    existing.write_text(json.dumps({"question_id": "cpa1-eval-accounting-001"}))
    q = {
        "exam": "CPA_1",
        "subject": "accounting",
        "unit": "lease",
        "stem": "본문",
        "choices": ["a", "b", "c", "d"],
        "correct_choice": 0,
        "rights_status": "synthetic_seed",
        "review_status": "ai_draft",
    }
    path = write_question(q, tmp_path)
    assert path.name == "cpa1-eval-accounting-002.evaluation_question.json"
    # 기존 파일 그대로
    assert json.loads(existing.read_text())["question_id"] == "cpa1-eval-accounting-001"


# ----- integration: generate → validate → write -----


def test_pipeline_with_validation_revise(tmp_path):
    """generate → validate(revise) → write 시 revised 본문이 저장돼야 한다."""
    spec = BatchSpec(subject="accounting", unit="lease", difficulty="hard", count=1)
    gen_invoke = lambda system, user: _fake_batch_json("lease", 1)

    revised_payload = {
        "stem": "수정된 본문",
        "choices": ["A1", "B1", "C1", "D1"],
        "correct_choice": 2,
    }
    val_invoke = lambda system, user: json.dumps(
        {"verdict": "revise", "issues": ["x"], "attractor_traps": ["t"], "revised": revised_payload}
    )

    [q] = generate_batch(spec, gen_invoke)
    r = validate_question(q, val_invoke)
    assert r.verdict == "revise"
    q.update(r.revised)
    q["attractor_traps"] = r.attractor_traps
    q["review_status"] = "ai_draft_revised"

    path = write_question(q, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["stem"] == "수정된 본문"
    assert data["correct_choice"] == 2
    assert data["review_status"] == "ai_draft_revised"
    assert data["attractor_traps"] == ["t"]
