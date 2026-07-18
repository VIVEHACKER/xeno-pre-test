"""exam_core 튜토리얼 사실 정확성 judge 단위 테스트."""

from __future__ import annotations

import json

from cpa_first.explain_gen.tutorial_judge import (
    build_judge_user,
    judge_tutorial,
    run_tutorial_judge_batch,
    summarize_tutorial_judgments,
)

TUTORIAL = {
    "tutorial_id": "tutorial_acct_revenue_exam_core",
    "subject_id": "cpa1_accounting",
    "subject_name": "회계학",
    "entry_topic": "수익인식",
    "ontology_node": "acct_revenue",
    "title": "수익인식 5단계",
    "objective": "K-IFRS 1115 5단계 모형을 적용한다.",
    "generated_by": "claude-fable-5/exam-core-workflow-2026-07",
    "concept_atoms": ["수익은 5단계로 인식한다."],
    "steps": [
        {
            "step_type": "worked_example",
            "title": "거래가격 배분",
            "difficulty": 3,
            "core_explanation": "K-IFRS 1115에 따라 거래가격을 개별판매가격 비율로 배분한다.",
            "prompt": "총 거래가격 100, 개별판매가격 A=60 B=40일 때 배분액은?",
            "model_answer": "A = 100 × 60/100 = 60, B = 100 × 40/100 = 40",
            "learner_action": "비율 계산",
            "checkpoints": ["개별판매가격", "비율", "배분"],
        }
    ],
}


def _invoke_returning(payload: dict):
    def invoke(system: str, user: str) -> str:
        # judge 입력에 스텝 콘텐츠가 실제로 담기는지
        assert "모범답안" in user
        assert "K-IFRS 1115" in user
        return "판정:\n```json\n" + json.dumps(payload, ensure_ascii=False) + "\n```"

    return invoke


def test_build_judge_user_serializes_steps():
    text = build_judge_user(TUTORIAL)
    assert "수익인식" in text
    assert "거래가격 배분" in text
    assert "A = 100 × 60/100 = 60" in text


def test_judge_clean():
    j = judge_tutorial(
        TUTORIAL,
        _invoke_returning(
            {
                "overall_verdict": "clean",
                "worked_example_recomputed": True,
                "step_findings": [],
                "expert_review_priority": 5,
                "summary": "오류 없음",
            }
        ),
        judge_model_label="codex:default",
    )
    assert j["overall_verdict"] == "clean"
    assert j["worked_example_recomputed"] is True
    assert j["severity_counts"] == {"critical": 0, "major": 0, "minor": 0, "uncertain": 0}


def test_judge_counts_severities():
    j = judge_tutorial(
        TUTORIAL,
        _invoke_returning(
            {
                "overall_verdict": "serious_errors",
                "worked_example_recomputed": True,
                "step_findings": [
                    {
                        "step_type": "worked_example",
                        "severity": "critical",
                        "category": "standard_citation",
                        "issue": "1115가 아니라 1116 인용",
                        "correction": "K-IFRS 1115가 맞음",
                    },
                    {
                        "step_type": "concept",
                        "severity": "uncertain",
                        "category": "factual",
                        "issue": "정의 모호",
                        "correction": "확인 필요",
                    },
                ],
                "expert_review_priority": 1,
                "summary": "기준서 오인용",
            }
        ),
    )
    assert j["overall_verdict"] == "serious_errors"
    assert j["severity_counts"]["critical"] == 1
    assert j["severity_counts"]["uncertain"] == 1


def test_judge_parse_failure_is_fail_closed():
    j = judge_tutorial(TUTORIAL, lambda s, u: "JSON 아님")
    assert j["overall_verdict"] == "judge_parse_failed"
    assert j["expert_review_priority"] == 1  # 파싱 실패는 최우선 수동 검토


def test_batch_checkpoint_and_summary(tmp_path):
    out = tmp_path / "judgments"
    ok = _invoke_returning(
        {
            "overall_verdict": "has_errors",
            "worked_example_recomputed": True,
            "step_findings": [
                {
                    "step_type": "worked_example",
                    "severity": "major",
                    "category": "calculation",
                    "issue": "배분 계산 오류",
                    "correction": "A=60이 맞음",
                }
            ],
            "expert_review_priority": 2,
            "summary": "계산 확인 필요",
        }
    )
    counts = run_tutorial_judge_batch([TUTORIAL], ok, out, judge_model_label="t")
    assert counts == {"skipped_existing": 0, "has_errors": 1}

    # 재실행 스킵
    def boom(s, u):
        raise AssertionError("호출되면 안 됨")

    counts2 = run_tutorial_judge_batch([TUTORIAL], boom, out)
    assert counts2 == {"skipped_existing": 1}

    summary = summarize_tutorial_judgments(out)
    assert summary["total_judged"] == 1
    assert summary["severity_total"]["major"] == 1
    assert summary["category_total"]["calculation"] == 1
    # 검수 큐에 major 상세 포함
    assert summary["review_queue"][0]["critical_and_major"][0]["category"] == "calculation"


def test_batch_backend_error_not_persisted(tmp_path):
    out = tmp_path / "judgments"

    def down(s, u):
        raise RuntimeError("connection refused")

    tuts = [dict(TUTORIAL, tutorial_id=f"t-{i}") for i in range(7)]
    counts = run_tutorial_judge_batch(tuts, down, out)
    assert counts["backend_error"] == 5  # Circuit Breaker
    assert list(out.rglob("*.tutorial_judgment.json")) == []
