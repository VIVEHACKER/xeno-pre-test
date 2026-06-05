"""eval_gen 모듈 단위 테스트.

live 모드 없이 invoke를 주입하여 결정론 테스트.
"""

from __future__ import annotations

import json

from cpa_first.eval_gen import (
    BatchSpec,
    ValidationResult,
    flag_if_questionable,
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
    invoke = lambda system, user: (
        f"여기 결과입니다:\n```json\n{_fake_batch_json('vat', 1)}\n```\n끝."
    )
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


# ----- 독립 모델 cross-check -----


def _reviewer_approve(system, user):
    return json.dumps({"verdict": "approve", "issues": [], "attractor_traps": []})


def test_cross_check_pass_with_independent_invoke():
    """독립 cross_check_invoke가 정답키와 일치 → cross_check_passed True."""
    q = {
        "stem": "s",
        "subject": "tax",
        "unit": "vat",
        "choices": ["a", "b", "c", "d"],
        "correct_choice": 2,
    }
    independent = lambda system, user: "풀이.\nANSWER: 2"
    r = validate_question(q, _reviewer_approve, cross_check=True, cross_check_invoke=independent)
    assert r.verdict == "approve"
    assert r.cross_check_passed is True
    assert r.cross_check_chosen == 2


def test_cross_check_fail_with_independent_invoke():
    """독립 모델이 정답키와 다른 답 → cross_check_passed False + issues 기록."""
    q = {
        "stem": "s",
        "subject": "tax",
        "unit": "vat",
        "choices": ["a", "b", "c", "d"],
        "correct_choice": 2,
    }
    independent = lambda system, user: "풀이.\nANSWER: 1"  # 키(2)와 불일치
    r = validate_question(q, _reviewer_approve, cross_check=True, cross_check_invoke=independent)
    assert r.cross_check_passed is False
    assert r.cross_check_chosen == 1
    assert any("cross_check_failed" in i for i in r.issues)


def test_cross_check_uses_independent_not_reviewer():
    """cross_check 풀이는 reviewer invoke가 아니라 독립 invoke로 호출돼야 한다."""
    calls = {"independent": 0}

    def independent(system, user):
        calls["independent"] += 1
        return "ANSWER: 0"

    q = {"stem": "s", "choices": ["a", "b"], "correct_choice": 0}
    validate_question(q, _reviewer_approve, cross_check=True, cross_check_invoke=independent)
    assert calls["independent"] == 1  # 독립 invoke가 정확히 1회 풀이


def test_flag_if_questionable_marks_disagreement():
    q = {"stem": "s", "correct_choice": 2}
    res = ValidationResult(
        verdict="approve",
        cross_check_passed=False,
        issues=["cross_check_failed: model chose 1, key=2"],
    )
    assert flag_if_questionable(q, res) is True
    assert q["flagged_questionable"] is True
    assert "cross_check_failed" in q["questionable_reason"]


def test_flag_if_questionable_noop_when_passed():
    q = {"stem": "s", "correct_choice": 2}
    res = ValidationResult(verdict="approve", cross_check_passed=True)
    assert flag_if_questionable(q, res) is False
    assert "flagged_questionable" not in q


def test_cross_check_handles_partial_revision():
    """revised가 부분 패치(stem만)여도 원본과 병합해 cross-check — KeyError/오플래그 없이."""
    partial = {"stem": "수정된 본문만"}  # choices/correct_choice 없는 부분 패치
    review = lambda system, user: json.dumps(
        {"verdict": "revise", "issues": [], "attractor_traps": [], "revised": partial}
    )
    independent = lambda system, user: "ANSWER: 1"  # 원본 correct_choice=1과 일치
    q = {
        "stem": "원본",
        "subject": "tax",
        "unit": "vat",
        "choices": ["a", "b", "c", "d"],
        "correct_choice": 1,
    }
    r = validate_question(q, review, cross_check=True, cross_check_invoke=independent)
    assert r.verdict == "revise"
    assert r.cross_check_passed is True  # 병합본(choices=원본, key=1) 기준 일치
    assert r.cross_check_chosen == 1


def test_validate_cross_check_passes_when_model_picks_key():
    """검토위원이 approve + 풀이 모델이 correct_choice와 같은 보기를 골랐을 때."""
    review_invoke = lambda system, user: json.dumps(
        {"verdict": "approve", "issues": [], "attractor_traps": []}
    )

    def cc_invoke(system, user):
        # correct_choice=2와 일치하도록 응답
        return "1회전 풀이.\n2회전 점검.\nANSWER: 2"

    q = {
        "question_id": "x",
        "subject": "tax",
        "unit": "corporate_tax",
        "stem": "임의",
        "choices": ["a", "b", "c", "d"],
        "correct_choice": 2,
    }
    r = validate_question(q, review_invoke, cross_check=True, cross_check_invoke=cc_invoke)
    assert r.verdict == "approve"
    assert r.cross_check_passed is True
    assert r.cross_check_chosen == 2


def test_validate_cross_check_fails_when_model_disagrees():
    """검토위원은 approve였지만 풀이 모델이 다른 보기를 골랐을 때."""
    review_invoke = lambda system, user: json.dumps(
        {"verdict": "approve", "issues": [], "attractor_traps": []}
    )

    def cc_invoke(system, user):
        # correct_choice=0인데 모델은 2를 고름 → cross_check_failed
        return "ANSWER: 2"

    q = {
        "question_id": "x",
        "subject": "tax",
        "unit": "corporate_tax",
        "stem": "임의",
        "choices": ["a", "b", "c", "d"],
        "correct_choice": 0,
    }
    r = validate_question(q, review_invoke, cross_check=True, cross_check_invoke=cc_invoke)
    assert r.cross_check_passed is False
    assert r.cross_check_chosen == 2
    assert any("cross_check_failed" in iss for iss in r.issues)


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
