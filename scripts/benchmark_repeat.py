"""세법(또는 임의 과목) 평가셋을 N회 반복 측정해 비결정성 분산을 정량화한다.

로컬 ollama 모델은 temperature=0에서도 int4 양자화/MLX 커널 비결정성으로
실행마다 답이 흔들린다. 단일 측정의 분산이 ±10%p 수준이라, RAG 효과(+7.7%p)를
확증하려면 같은 설정을 여러 번 돌려 평균±표준편차와 다수결을 봐야 한다.

핵심 설계:
- 문항별 N회 결과를 jsonl에 **즉시 append** → 장시간 실행 중 중단/삭제돼도 복구.
- 집계: run별 정답률(평균±표준편차), 문항별 안정성(항상맞음/흔들림/항상틀림),
  다수결 정답률(per-question majority vote).

사용:
    .venv/bin/python scripts/benchmark_repeat.py --model qwen3.5:27b-int4 \\
        --ids-file /tmp/tax_all.txt --rag data/seeds/rag \\
        --num-predict 16000 --num-ctx 24000 --timeout 3000 --runs 3 \\
        --jsonl data/runtime/benchmark_runs/tax39-repeat3.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

# benchmark_local.py의 ollama invoke 재사용 (중복 구현 방지)
from benchmark_local import make_invoke

from cpa_first.benchmark.runner import grade
from cpa_first.solver.solver import Solver, load_evaluation_questions


def _load_done(jsonl_path: Path) -> set[tuple[str, int]]:
    """이미 측정된 (question_id, run_idx) 집합. 재개 시 스킵용."""
    done: set[tuple[str, int]] = set()
    if jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                done.add((rec["question_id"], rec["run"]))
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.5:27b-int4")
    ap.add_argument("--eval-dir", default="data/seeds/evaluation")
    ap.add_argument("--ids-file", default="", help="줄단위 question_id 파일")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--num-predict", type=int, default=16000)
    ap.add_argument("--num-ctx", type=int, default=24000)
    ap.add_argument("--timeout", type=int, default=3000)
    ap.add_argument("--rag", default="")
    ap.add_argument(
        "--jsonl",
        default="data/runtime/benchmark_runs/repeat.jsonl",
        help="문항별 결과 즉시 append (재개 가능)",
    )
    ap.add_argument("--out", default="", help="최종 집계 JSON")
    args = ap.parse_args()

    questions = load_evaluation_questions(args.eval_dir)
    if args.ids_file:
        ids = {ln.strip() for ln in Path(args.ids_file).read_text().splitlines() if ln.strip()}
        questions = [q for q in questions if q["question_id"] in ids]

    rag_chunks: list = []
    if args.rag:
        from cpa_first.rag import load_chunks

        rag_chunks = load_chunks(Path(args.rag))
        print(f"[rag] {len(rag_chunks)} chunks loaded", file=sys.stderr)

    solver = Solver(
        mode="live",
        model=args.model,
        invoke=make_invoke(
            args.model,
            num_predict=args.num_predict,
            num_ctx=args.num_ctx,
            timeout=args.timeout,
        ),
        rag_chunks=rag_chunks,
    )

    jsonl_path = Path(args.jsonl)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    done = _load_done(jsonl_path)
    if done:
        print(f"[resume] {len(done)} (qid,run) already measured — skipping", file=sys.stderr)

    total_cells = len(questions) * args.runs
    t0 = time.monotonic()
    cell = 0
    # run-major 순서: run 1 전체 → run 2 전체 ... (각 run이 독립 측정으로 해석되게)
    for run in range(1, args.runs + 1):
        for q in questions:
            cell += 1
            key = (q["question_id"], run)
            if key in done:
                continue
            qt0 = time.monotonic()
            try:
                res = solver.solve(q)
                chosen = res.chosen_index
                ok = grade(q, res).correct
            except Exception as exc:  # noqa: BLE001
                chosen = -1
                ok = False
                print(f"  ERROR {q['question_id']} run{run}: {exc}", file=sys.stderr, flush=True)
            dt = time.monotonic() - qt0
            rec = {
                "question_id": q["question_id"],
                "subject": q["subject"],
                "run": run,
                "chosen": chosen,
                "correct_choice": q.get("correct_choice"),
                "ok": ok,
                "secs": round(dt, 1),
            }
            with jsonl_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            elapsed = time.monotonic() - t0
            print(
                f"[{cell}/{total_cells}] run{run} {'O' if ok else 'X'} "
                f"{q['question_id']:26s} chose={chosen} ans={q.get('correct_choice')} "
                f"{dt:.0f}s (elapsed {elapsed / 3600:.1f}h)",
                file=sys.stderr,
                flush=True,
            )

    _aggregate(jsonl_path, questions, args)
    return 0


def _aggregate(jsonl_path: Path, questions: list, args) -> None:
    recs = [
        json.loads(ln) for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()
    ]
    # run별 정답률
    run_correct: dict[int, list[bool]] = defaultdict(list)
    # 문항별 run→ok
    q_runs: dict[str, list[bool]] = defaultdict(list)
    q_choices: dict[str, list[int]] = defaultdict(list)
    for r in recs:
        run_correct[r["run"]].append(r["ok"])
        q_runs[r["question_id"]].append(r["ok"])
        q_choices[r["question_id"]].append(r["chosen"])

    n_q = len(questions)
    run_acc = {run: round(sum(v) / len(v) * 100, 1) for run, v in sorted(run_correct.items())}
    accs = list(run_acc.values())
    mean_acc = round(statistics.mean(accs), 1) if accs else 0.0
    stdev_acc = round(statistics.pstdev(accs), 1) if len(accs) > 1 else 0.0

    # 문항 안정성 분류
    always_right = [q for q, v in q_runs.items() if all(v)]
    always_wrong = [q for q, v in q_runs.items() if not any(v)]
    flaky = [q for q, v in q_runs.items() if any(v) and not all(v)]

    # 다수결 정답률: 문항별 과반 run이 정답이면 정답
    majority_correct = sum(1 for q, v in q_runs.items() if sum(v) * 2 > len(v))
    majority_acc = round(majority_correct / n_q * 100, 1) if n_q else 0.0

    summary = {
        "model": args.model,
        "runs": args.runs,
        "n_questions": n_q,
        "rag": bool(args.rag),
        "run_accuracy_pct": run_acc,
        "mean_accuracy_pct": mean_acc,
        "stdev_accuracy_pct": stdev_acc,
        "majority_vote_accuracy_pct": majority_acc,
        "stability": {
            "always_right": len(always_right),
            "always_wrong": len(always_wrong),
            "flaky": len(flaky),
            "flaky_ids": sorted(flaky),
        },
    }
    out = args.out or str(jsonl_path).replace(".jsonl", "-summary.json")
    Path(out).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n집계 저장: {out}")


if __name__ == "__main__":
    raise SystemExit(main())
