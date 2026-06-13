"""라우팅 solver(과목별 백엔드) E2E 벤치마크 — 제품 경로 그대로 실측한다.

benchmark_local.py와 달리 자체 invoke를 만들지 않고 create_routing_solver()를
그대로 사용한다. 즉 llm.py 어댑터(ollama options 포함)까지 제품 코드 경로를 검증한다.

사용:
    CPA_OLLAMA_MODEL=qwen3.5:27b-int4 .venv/bin/python scripts/benchmark_routing.py \\
        --routes tax:codex --default ollama --rag data/seeds/rag --per-subject 2
    # 전체 159문항:
    CPA_OLLAMA_MODEL=qwen3.5:27b-int4 .venv/bin/python scripts/benchmark_routing.py \\
        --routes tax:codex --default ollama --rag data/seeds/rag --per-subject 0
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from cpa_first.benchmark.runner import grade
from cpa_first.solver.routing import create_routing_solver, parse_routes
from cpa_first.solver.solver import load_evaluation_questions


def stratified(questions: list[dict], per_subject: int) -> list[dict]:
    """과목별 앞에서 N개. 0이면 전체. 결정론(파일명 정렬 순)."""
    if per_subject <= 0:
        return questions
    by_subject: dict[str, list[dict]] = {}
    for q in questions:
        by_subject.setdefault(q["subject"], []).append(q)
    picked: list[dict] = []
    for subject in sorted(by_subject):
        picked.extend(by_subject[subject][:per_subject])
    return picked


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--routes", default="tax:codex", help='"과목:백엔드,..." 형식')
    ap.add_argument("--default", default="ollama", help="라우트 외 과목 백엔드")
    ap.add_argument("--eval-dir", default="data/seeds/evaluation")
    ap.add_argument(
        "--questions-files",
        default="",
        help="쉼표구분 JSON 배열 파일 경로 — 실기출(parsed) 등 비-시드 문항 채점용. 지정 시 --eval-dir 무시",
    )
    ap.add_argument("--rag", default="data/seeds/rag")
    ap.add_argument(
        "--skip-math-lossy",
        action="store_true",
        help="수식이 PUA 글리프로 유실된 문항 제외 (실기출 PDF 추출 한계 — 텍스트로 풀이 불가)",
    )
    ap.add_argument("--per-subject", type=int, default=2, help="과목별 표본 수(0=전체)")
    ap.add_argument("--ids", default="", help="쉼표구분 question_id만 채점(표본 무시)")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    if args.questions_files:
        questions = []
        for fp in args.questions_files.split(","):
            fp = fp.strip()
            if fp:
                questions.extend(json.loads(Path(fp).read_text(encoding="utf-8")))
    else:
        questions = load_evaluation_questions(args.eval_dir)
    if args.skip_math_lossy:
        skipped = sum(1 for q in questions if q.get("math_lossy"))
        questions = [q for q in questions if not q.get("math_lossy")]
        print(f"[skip] math_lossy {skipped}문항 제외", file=sys.stderr)
    if args.ids:
        wanted = {x.strip() for x in args.ids.split(",") if x.strip()}
        questions = [q for q in questions if q["question_id"] in wanted]
    else:
        questions = stratified(questions, args.per_subject)

    routes = parse_routes(args.routes)
    solver = create_routing_solver(
        routes,
        default_backend=args.default,
        rag_dir=Path(args.rag) if args.rag else None,
    )
    print(
        f"[routing] routes={solver.route_labels} default={args.default} questions={len(questions)}",
        file=sys.stderr,
        flush=True,
    )

    rows: list[dict] = []
    per_subject: dict[str, list[int]] = {}
    t0 = time.monotonic()
    correct = 0
    for i, q in enumerate(questions, 1):
        backend = solver.route_labels.get(q["subject"], args.default)
        qt0 = time.monotonic()
        try:
            res = solver.solve(q)
            score = grade(q, res)
            ok = score.correct
            chosen = score.chosen_index
        except Exception as exc:  # noqa: BLE001 — 개별 문항 실패는 기록 후 계속
            print(f"[{i}/{len(questions)}] ERROR {q['question_id']}: {exc}", file=sys.stderr)
            ok, chosen = False, -1
        dt = time.monotonic() - qt0
        correct += int(ok)
        per_subject.setdefault(q["subject"], []).append(int(ok))
        rows.append(
            {
                "question_id": q["question_id"],
                "subject": q["subject"],
                "backend": backend,
                "correct": ok,
                "chosen": chosen,
                "expected": q["correct_choice"],
                "secs": round(dt, 1),
            }
        )
        print(
            f"[{i}/{len(questions)}] {q['question_id']} → {backend} "
            f"{'O' if ok else 'X'} ({dt:.0f}s)",
            file=sys.stderr,
            flush=True,
        )

    total = len(questions)
    summary = {
        "mode": "routing",
        "routes": solver.route_labels,
        "default_backend": args.default,
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "elapsed_secs": round(time.monotonic() - t0, 1),
        "per_subject": {
            s: {"n": len(v), "correct": sum(v), "accuracy": round(sum(v) / len(v), 4)}
            for s, v in sorted(per_subject.items())
        },
        "rows": rows,
    }
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False))
    if args.out:
        Path(args.out).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[saved] {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
