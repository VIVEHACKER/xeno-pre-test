"""해설 품질 judge 단위 테스트 — right-answer-wrong-reasoning 검출 축."""

from __future__ import annotations

import json

from cpa_first.explain_gen.judge import (
    judge_explanation,
    run_judge_batch,
    summarize_judgments,
)

QUESTION = {
    "question_id": "cpa1-real-2026-tax-001",
    "subject": "tax",
    "applicable_year": 2026,
    "stem": "손금 산입 항목은?",
    "choices": ["벌금", "한도초과 접대비", "한도 내 감가상각비", "임원상여 한도초과", "부담금"],
    "correct_choice": 2,
}

RECORD = {
    "question_id": "cpa1-real-2026-tax-001",
    "subject": "tax",
    "applicable_year": 2026,
    "model": "ollama:qwen3.5:27b-int4",
    "walkthrough": "감가상각비는 한도 내에서 손금 산입된다. ANSWER: 2",
}


def _invoke_returning(payload: dict):
    def invoke(system: str, user: str) -> str:
        # judge 프롬프트에 정답과 해설이 실제로 담기는지 확인
        assert "공식 정답" in user
        assert "감가상각비" in user
        return "채점 결과:\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"

    return invoke


def test_judge_pass():
    j = judge_explanation(
        RECORD,
        QUESTION,
        _invoke_returning(
            {
                "reasoning_correct": True,
                "errors": [],
                "completeness": 4,
                "verdict": "pass",
                "one_line": "논거 타당",
            }
        ),
        judge_model_label="codex:default",
    )
    assert j["verdict"] == "pass"
    assert j["reasoning_correct"] is True
    assert j["judge_model"] == "codex:default"


def test_judge_fail_records_errors():
    j = judge_explanation(
        RECORD,
        QUESTION,
        _invoke_returning(
            {
                "reasoning_correct": False,
                "errors": ["법인세법 조문 인용 오류"],
                "completeness": 2,
                "verdict": "fail",
                "one_line": "우연 정답",
            }
        ),
    )
    assert j["verdict"] == "fail"
    assert j["errors"] == ["법인세법 조문 인용 오류"]


def test_judge_parse_failure_is_fail_closed():
    j = judge_explanation(RECORD, QUESTION, lambda s, u: "JSON 아님")
    assert j["verdict"] == "judge_parse_failed"  # 조용한 pass 금지


def test_judge_batch_checkpoint_and_summary(tmp_path):
    out = tmp_path / "judgments"
    pairs = [(RECORD, QUESTION)]
    ok = _invoke_returning(
        {
            "reasoning_correct": True,
            "errors": [],
            "completeness": 5,
            "verdict": "pass",
            "one_line": "ok",
        }
    )
    counts = run_judge_batch(pairs, ok, out, judge_model_label="t")
    assert counts == {"skipped_existing": 0, "pass": 1}

    # 재실행 스킵
    def boom(s, u):
        raise AssertionError("호출되면 안 됨")

    counts2 = run_judge_batch(pairs, boom, out)
    assert counts2 == {"skipped_existing": 1}

    summary = summarize_judgments(out)
    assert summary["total"] == 1
    assert summary["pass_rate"] == 1.0


def test_judge_batch_backend_error_not_persisted(tmp_path):
    out = tmp_path / "judgments"

    def down(s, u):
        raise RuntimeError("connection refused")

    pairs = [(dict(RECORD, question_id=f"q-{i}"), QUESTION) for i in range(7)]
    counts = run_judge_batch(pairs, down, out)
    assert counts["backend_error"] == 5  # 연속 5회에서 중단
    assert list(out.rglob("*.judgment.json")) == []
