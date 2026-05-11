"""벤치마크 러너 통합 테스트."""

from __future__ import annotations

from pathlib import Path

import pytest

from cpa_first.benchmark import run_benchmark
from cpa_first.solver import Solver


ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "data" / "seeds" / "evaluation"


QUESTIONS = [
    {
        "question_id": "bm-1",
        "exam": "CPA_1",
        "subject": "accounting",
        "unit": "u",
        "stem": "x",
        "choices": ["a", "b", "c", "d"],
        "correct_choice": 0,
        "rights_status": "synthetic_seed",
        "review_status": "expert_reviewed",
    },
    {
        "question_id": "bm-2",
        "exam": "CPA_1",
        "subject": "accounting",
        "unit": "u",
        "stem": "y",
        "choices": ["a", "b", "c", "d"],
        "correct_choice": 1,
        "rights_status": "synthetic_seed",
        "review_status": "expert_reviewed",
    },
    {
        "question_id": "bm-3",
        "exam": "CPA_1",
        "subject": "tax",
        "unit": "u",
        "stem": "z",
        "choices": ["a", "b", "c", "d"],
        "correct_choice": 2,
        "rights_status": "synthetic_seed",
        "review_status": "expert_reviewed",
    },
]


def test_stub_solver_always_first_choice(tmp_path: Path):
    """stub은 항상 0번 → bm-1만 맞고 bm-2/bm-3은 틀림."""
    result = run_benchmark(
        QUESTIONS,
        solver=Solver(mode="stub"),
        runs_dir=tmp_path,
    )
    assert result.total == 3
    assert result.correct == 1
    assert result.per_subject["accounting"]["accuracy"] == 0.5
    assert result.per_subject["tax"]["accuracy"] == 0.0


def test_mock_solver_deterministic_score(tmp_path: Path):
    """mock 모드도 question_id 해시 기반 결정론. 동일 입력 동일 점수."""
    a = run_benchmark(
        QUESTIONS, solver=Solver(mode="mock"), runs_dir=tmp_path / "a"
    )
    b = run_benchmark(
        QUESTIONS, solver=Solver(mode="mock"), runs_dir=tmp_path / "b"
    )
    assert a.overall_accuracy == b.overall_accuracy


def test_run_persists_artifact(tmp_path: Path):
    run = run_benchmark(QUESTIONS, solver=Solver(mode="stub"), runs_dir=tmp_path)
    artifact = tmp_path / f"{run.run_id}.json"
    assert artifact.exists()


def test_pass_status_threshold():
    """모든 정답이 0번이면 stub 솔버는 100% — 합격."""
    questions = [
        dict(q, correct_choice=0) for q in QUESTIONS
    ]
    run = run_benchmark(questions, solver=Solver(mode="stub"), persist=False)
    assert run.overall_accuracy == 1.0
    assert run.pass_status["would_pass"] is True


def test_pass_status_per_subject_block():
    """과목별 임계 미달이면 전체 통과해도 would_pass False."""
    questions = [
        # accounting 100%
        dict(QUESTIONS[0], correct_choice=0),
        dict(QUESTIONS[1], correct_choice=0),
        # tax 0% (정답을 0번 아닌 데로)
        dict(QUESTIONS[2], correct_choice=2),
    ]
    run = run_benchmark(questions, solver=Solver(mode="stub"), persist=False)
    # stub은 항상 0번. accounting 둘 다 맞고 tax는 틀림.
    assert run.per_subject["tax"]["accuracy"] == 0.0
    assert run.pass_status["would_pass"] is False


def test_real_seeds_run_with_stub(tmp_path: Path):
    """실제 평가 시드 5건이 벤치마크 파이프라인을 통과한다 (정답률은 별개)."""
    run = run_benchmark(eval_dir=EVAL_DIR, solver=Solver(mode="stub"), runs_dir=tmp_path)
    assert run.total >= 5
    assert "accounting" in run.per_subject
    assert "tax" in run.per_subject


def test_grade_records_chosen_and_correct(tmp_path: Path):
    run = run_benchmark(QUESTIONS, solver=Solver(mode="stub"), runs_dir=tmp_path)
    for score in run.questions:
        assert score.chosen_index == 0
    correctness = {s.question_id: s.correct for s in run.questions}
    assert correctness == {"bm-1": True, "bm-2": False, "bm-3": False}


def test_empty_questions_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        run_benchmark([], solver=Solver(mode="stub"), runs_dir=tmp_path)
