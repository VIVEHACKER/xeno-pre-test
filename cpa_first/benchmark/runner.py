"""평가 문제 → solver → 채점 → 점수 보고.

CLI 예:
    python -m cpa_first.benchmark.runner
    python -m cpa_first.benchmark.runner --mode stub
    CPA_SOLVER_MODE=live python -m cpa_first.benchmark.runner
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from cpa_first.solver import create_solver, load_evaluation_questions
from cpa_first.solver.solver import Solver, SolveResult

load_dotenv()


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVAL_DIR = ROOT / "data" / "seeds" / "evaluation"
DEFAULT_RUNS_DIR = ROOT / "data" / "runtime" / "benchmark_runs"

# 합격선 (CPA 1차 가정. 모의 평가셋 기준)
PASS_THRESHOLD_PER_SUBJECT = 0.40
PASS_THRESHOLD_AVERAGE = 0.60


@dataclass
class QuestionScore:
    question_id: str
    subject: str
    unit: str
    correct: bool
    chosen_index: int
    correct_index: int
    rationale: str
    difficulty: str | None = None
    bloom_level: str | None = None


@dataclass
class BenchmarkResult:
    run_id: str
    started_at: str
    finished_at: str
    solver_mode: str
    solver_model: str | None
    total: int
    correct: int
    overall_accuracy: float
    per_subject: dict[str, dict[str, float]]
    per_difficulty: dict[str, dict[str, float]]
    per_bloom: dict[str, dict[str, float]]
    per_unit: dict[str, dict[str, float]]
    pass_status: dict[str, Any]
    questions: list[QuestionScore] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def grade(question: dict[str, Any], result: SolveResult) -> QuestionScore:
    correct = result.chosen_index == question["correct_choice"]
    return QuestionScore(
        question_id=question["question_id"],
        subject=question["subject"],
        unit=question["unit"],
        correct=correct,
        chosen_index=result.chosen_index,
        correct_index=question["correct_choice"],
        rationale=result.rationale[:500],
        difficulty=question.get("difficulty"),
        bloom_level=question.get("bloom_level"),
    )


def _group_accuracy(
    scores: list[QuestionScore],
    key: Callable[[QuestionScore], str | None],
) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    buckets: dict[str, list[QuestionScore]] = {}
    for s in scores:
        k = key(s)
        if k is None:
            continue
        buckets.setdefault(k, []).append(s)
    for k in sorted(buckets.keys()):
        items = buckets[k]
        correct = sum(1 for s in items if s.correct)
        out[k] = {
            "total": len(items),
            "correct": correct,
            "accuracy": round(correct / len(items), 4) if items else 0.0,
        }
    return out


def _summarize_subjects(scores: list[QuestionScore]) -> dict[str, dict[str, float]]:
    return _group_accuracy(scores, key=lambda s: s.subject)


def _pass_status(per_subject: dict[str, dict[str, float]], overall: float) -> dict[str, Any]:
    """단순 합격선 비교 (모의 평가셋 기준)."""
    subject_pass = {
        subject: stats["accuracy"] >= PASS_THRESHOLD_PER_SUBJECT
        for subject, stats in per_subject.items()
    }
    overall_pass = overall >= PASS_THRESHOLD_AVERAGE
    all_subject_pass = all(subject_pass.values()) if subject_pass else False
    return {
        "per_subject_threshold": PASS_THRESHOLD_PER_SUBJECT,
        "overall_threshold": PASS_THRESHOLD_AVERAGE,
        "per_subject_pass": subject_pass,
        "overall_pass": overall_pass,
        "would_pass": overall_pass and all_subject_pass,
    }


def run_benchmark(
    questions: list[dict[str, Any]] | None = None,
    *,
    solver: Solver | None = None,
    eval_dir: Path | None = None,
    runs_dir: Path | None = None,
    persist: bool = True,
) -> BenchmarkResult:
    if questions is None:
        questions = load_evaluation_questions(eval_dir or DEFAULT_EVAL_DIR)
    if not questions:
        raise ValueError("no evaluation questions to grade")
    if solver is None:
        solver = create_solver()

    started_at = _now_iso()
    scores: list[QuestionScore] = []
    for q in questions:
        result = solver.solve(q)
        scores.append(grade(q, result))

    correct = sum(1 for s in scores if s.correct)
    overall = correct / len(scores)
    per_subject = _summarize_subjects(scores)
    per_difficulty = _group_accuracy(scores, key=lambda s: s.difficulty)
    per_bloom = _group_accuracy(scores, key=lambda s: s.bloom_level)
    per_unit = _group_accuracy(scores, key=lambda s: f"{s.subject}/{s.unit}")
    pass_status = _pass_status(per_subject, overall)
    finished_at = _now_iso()

    result = BenchmarkResult(
        run_id=_run_id(),
        started_at=started_at,
        finished_at=finished_at,
        solver_mode=solver.mode,
        solver_model=solver.model if solver.mode == "live" else None,
        total=len(scores),
        correct=correct,
        overall_accuracy=round(overall, 4),
        per_subject=per_subject,
        per_difficulty=per_difficulty,
        per_bloom=per_bloom,
        per_unit=per_unit,
        pass_status=pass_status,
        questions=scores,
    )

    if persist:
        target_dir = runs_dir or DEFAULT_RUNS_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{result.run_id}.json"
        with path.open("w", encoding="utf-8") as f:
            json.dump(
                _serialize(result),
                f,
                ensure_ascii=False,
                indent=2,
            )

    return result


def _serialize(result: BenchmarkResult) -> dict[str, Any]:
    payload = asdict(result)
    return payload


def cli() -> int:
    parser = argparse.ArgumentParser(description="CPA First 응시자 벤치마크")
    parser.add_argument("--mode", choices=["mock", "stub", "live"], default=None)
    parser.add_argument("--eval-dir", type=Path, default=None)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    solver = create_solver(mode=args.mode) if args.mode else create_solver()
    result = run_benchmark(
        eval_dir=args.eval_dir,
        solver=solver,
        persist=not args.no_persist,
    )

    print(f"run_id     : {result.run_id}")
    print(f"mode       : {result.solver_mode}")
    if result.solver_model:
        print(f"model      : {result.solver_model}")
    print(f"questions  : {result.total} (correct {result.correct})")
    print(f"overall    : {result.overall_accuracy * 100:.1f}%")
    print()
    print("[by subject]")
    for subject, stats in result.per_subject.items():
        print(f"  - {subject:<10} {stats['correct']}/{int(stats['total'])} "
              f"= {stats['accuracy'] * 100:.1f}%")
    if result.per_difficulty:
        print()
        print("[by difficulty]")
        for diff in ("easy", "mid", "hard"):
            if diff not in result.per_difficulty:
                continue
            stats = result.per_difficulty[diff]
            print(f"  - {diff:<10} {stats['correct']}/{int(stats['total'])} "
                  f"= {stats['accuracy'] * 100:.1f}%")
    if result.per_bloom:
        print()
        print("[by bloom level]")
        for level, stats in result.per_bloom.items():
            print(f"  - {level:<10} {stats['correct']}/{int(stats['total'])} "
                  f"= {stats['accuracy'] * 100:.1f}%")
    print()
    print(f"would pass : {result.pass_status['would_pass']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
