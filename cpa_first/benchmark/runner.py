"""평가 문제 → solver → 채점 → 점수 보고.

CLI 예:
    python -m cpa_first.benchmark.runner
    python -m cpa_first.benchmark.runner --mode stub
    CPA_SOLVER_MODE=live python -m cpa_first.benchmark.runner
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from cpa_first.solver import create_solver, load_evaluation_questions
from cpa_first.solver.solver import Solver, SolveResult


# 풀이 품질 객관 지표용 정규식.
# K-IFRS 1xxx호, 법인세법/소득세법/부가가치세법/상법/국세기본법 등 조문 인용 탐지.
_CITATION_PATTERNS = [
    re.compile(r"K[-\s]?IFRS\s*1\d{3}호?", re.IGNORECASE),
    re.compile(r"기업회계기준서"),
    re.compile(r"(법인세법|소득세법|부가가치세법|상속세\s*및\s*증여세법|국세기본법|상법|국제조세조정)(\s*시행령|\s*시행규칙)?\s*제\s*\d+조"),
    re.compile(r"제\s*\d+조의?\s*\d*"),
]
_INSUFFICIENT_RE = re.compile(r"INSUFFICIENT\s+EVIDENCE", re.IGNORECASE)
_ANSWER_LINE_RE = re.compile(r"ANSWER\s*:\s*\d+", re.IGNORECASE)

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
    rationale: str  # 풀이 전체 보존 (자르지 않음)
    difficulty: str | None = None
    bloom_level: str | None = None
    # 풀이 품질 객관 지표 (per-question)
    rationale_chars: int = 0
    citation_count: int = 0
    insufficient_evidence: bool = False
    answer_parse_ok: bool = False
    # 오답 분석: 매력적 오답 함정에 빠졌는지 (attractor_traps에 chosen_choice가 매칭되는지)
    attractor_hit: bool | None = None
    # 평가셋 자체 품질 의심 문항. true면 메인 채점에서 제외하고 별도 카운트.
    flagged_questionable: bool = False
    questionable_reason: str | None = None


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
    quality_metrics: dict[str, Any] = field(default_factory=dict)
    questions: list[QuestionScore] = field(default_factory=list)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _count_citations(text: str) -> int:
    return sum(len(p.findall(text)) for p in _CITATION_PATTERNS)


def _attractor_hit(question: dict[str, Any], chosen_index: int, correct: bool) -> bool | None:
    """오답이 출제자가 의도한 매력적 오답에 매칭되는지.

    attractor_traps이 없으면 None. 정답이면 False(함정에 안 빠짐).
    """
    traps = question.get("attractor_traps")
    if not traps:
        return None
    if correct:
        return False
    if not (0 <= chosen_index < len(question.get("choices", []))):
        return False
    chosen_text = question["choices"][chosen_index]
    # 함정 텍스트와 선택지 텍스트의 부분 매칭 또는 함정 내 키워드가 선택지 안에 있는지.
    for trap in traps:
        if not isinstance(trap, str):
            continue
        # 길이 4자 이상의 부분문자열이 양쪽에 등장하면 함정 hit으로 간주.
        for token in re.split(r"[\s,·]+", trap):
            token = token.strip()
            if len(token) >= 4 and token in chosen_text:
                return True
    return False


def grade(question: dict[str, Any], result: SolveResult) -> QuestionScore:
    correct = result.chosen_index == question["correct_choice"]
    raw = result.raw_response or result.rationale
    return QuestionScore(
        question_id=question["question_id"],
        subject=question["subject"],
        unit=question["unit"],
        correct=correct,
        chosen_index=result.chosen_index,
        correct_index=question["correct_choice"],
        rationale=raw,  # 풀이 전체 보존
        difficulty=question.get("difficulty"),
        bloom_level=question.get("bloom_level"),
        rationale_chars=len(raw),
        citation_count=_count_citations(raw),
        insufficient_evidence=bool(_INSUFFICIENT_RE.search(raw)),
        answer_parse_ok=bool(_ANSWER_LINE_RE.search(raw)) and result.chosen_index >= 0,
        attractor_hit=_attractor_hit(question, result.chosen_index, correct),
        flagged_questionable=bool(question.get("flagged_questionable")),
        questionable_reason=question.get("questionable_reason"),
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


def _compute_quality_metrics(scores: list[QuestionScore]) -> dict[str, Any]:
    """풀이 품질 객관 지표 산출. 모든 비율은 [0, 1].

    answer_parse_rate: ANSWER 라인 파싱 성공 비율 (낮으면 출력 포맷 위반 문제 큼)
    insufficient_evidence_rate: 모델이 명시적으로 근거 부족 선언한 비율
    avg_rationale_chars: 풀이 평균 길이(자) — 너무 짧으면 추측 가능성
    avg_citation_count: 회계기준/조문 평균 인용 횟수 — 객관 근거 깊이 신호
    answered_with_citation_rate: 1회 이상 조문/기준 인용한 비율
    attractor_hit_rate_among_wrong: 오답 중 매력적 오답에 빠진 비율 (attractor_traps 보유 문항 대상)
    """
    n = len(scores)
    if n == 0:
        return {}
    rationale_chars = [s.rationale_chars for s in scores]
    citation_counts = [s.citation_count for s in scores]
    wrong_with_traps = [s for s in scores if not s.correct and s.attractor_hit is not None]
    attractor_hits = sum(1 for s in wrong_with_traps if s.attractor_hit)
    return {
        "answer_parse_rate": round(sum(1 for s in scores if s.answer_parse_ok) / n, 4),
        "insufficient_evidence_rate": round(sum(1 for s in scores if s.insufficient_evidence) / n, 4),
        "avg_rationale_chars": round(sum(rationale_chars) / n, 1),
        "min_rationale_chars": min(rationale_chars),
        "max_rationale_chars": max(rationale_chars),
        "avg_citation_count": round(sum(citation_counts) / n, 2),
        "answered_with_citation_rate": round(sum(1 for c in citation_counts if c > 0) / n, 4),
        "attractor_traps_evaluated": len(wrong_with_traps),
        "attractor_hit_rate_among_wrong": round(attractor_hits / len(wrong_with_traps), 4) if wrong_with_traps else None,
    }


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
    total = len(questions)
    progress_every = max(1, total // 20)  # 5% 단위 진행률
    import sys
    import time as _time
    t0 = _time.monotonic()
    for idx, q in enumerate(questions, start=1):
        try:
            result = solver.solve(q)
        except Exception as exc:  # noqa: BLE001 — solver 실패 한 건이 전체를 끊지 않게
            result = SolveResult(
                question_id=q["question_id"],
                chosen_index=-1,
                rationale=f"[SOLVER ERROR] {type(exc).__name__}: {exc}",
                mode=solver.mode,
                model=solver.model if solver.mode == "live" else None,
                raw_response="",
            )
        scores.append(grade(q, result))
        if idx % progress_every == 0 or idx == total:
            elapsed = _time.monotonic() - t0
            rate = idx / elapsed if elapsed > 0 else 0.0
            eta = (total - idx) / rate if rate > 0 else 0.0
            print(
                f"[bench] {idx}/{total} ({idx*100//total}%) "
                f"elapsed={elapsed:.0f}s eta={eta:.0f}s",
                file=sys.stderr,
                flush=True,
            )

    # 평가셋 자체 품질 의심 문항은 메인 채점에서 제외. 별도 카운트로 보존.
    flagged_scores = [s for s in scores if s.flagged_questionable]
    graded_scores = [s for s in scores if not s.flagged_questionable]
    if not graded_scores:
        raise ValueError("all questions are flagged_questionable — nothing to grade")

    correct = sum(1 for s in graded_scores if s.correct)
    overall = correct / len(graded_scores)
    per_subject = _summarize_subjects(graded_scores)
    per_difficulty = _group_accuracy(graded_scores, key=lambda s: s.difficulty)
    per_bloom = _group_accuracy(graded_scores, key=lambda s: s.bloom_level)
    per_unit = _group_accuracy(graded_scores, key=lambda s: f"{s.subject}/{s.unit}")
    pass_status = _pass_status(per_subject, overall)
    quality_metrics = _compute_quality_metrics(graded_scores)
    quality_metrics["flagged_excluded"] = len(flagged_scores)
    quality_metrics["flagged_reasons"] = sorted({
        (s.questionable_reason or "unspecified") for s in flagged_scores
    })
    finished_at = _now_iso()

    result = BenchmarkResult(
        run_id=_run_id(),
        started_at=started_at,
        finished_at=finished_at,
        solver_mode=solver.mode,
        solver_model=solver.model if solver.mode == "live" else None,
        total=len(graded_scores),
        correct=correct,
        overall_accuracy=round(overall, 4),
        per_subject=per_subject,
        per_difficulty=per_difficulty,
        per_bloom=per_bloom,
        per_unit=per_unit,
        pass_status=pass_status,
        quality_metrics=quality_metrics,
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
    parser.add_argument("--mode", choices=["reasoned", "mock", "stub", "live"], default=None)
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
    flagged = result.quality_metrics.get("flagged_excluded", 0) if result.quality_metrics else 0
    if flagged:
        print(f"flagged    : {flagged} (제외, 별도 보고)")
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
    if result.quality_metrics:
        print()
        print("[rationale quality]")
        qm = result.quality_metrics
        print(f"  answer_parse_rate         : {qm['answer_parse_rate'] * 100:.1f}%")
        print(f"  insufficient_evidence_rate: {qm['insufficient_evidence_rate'] * 100:.1f}%")
        print(f"  avg_rationale_chars       : {qm['avg_rationale_chars']:.0f} (min {qm['min_rationale_chars']}, max {qm['max_rationale_chars']})")
        print(f"  avg_citation_count        : {qm['avg_citation_count']:.2f}")
        print(f"  answered_with_citation    : {qm['answered_with_citation_rate'] * 100:.1f}%")
        if qm.get("attractor_hit_rate_among_wrong") is not None:
            print(
                f"  attractor_hit_among_wrong : "
                f"{qm['attractor_hit_rate_among_wrong'] * 100:.1f}% "
                f"(n={qm['attractor_traps_evaluated']})"
            )
    print()
    print(f"would pass : {result.pass_status['would_pass']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
