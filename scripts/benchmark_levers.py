"""세법 약점 보강 레버 통합 실험.

4개 레버를 한 스크립트로 검증한다:
  1. 계산 단계강제 프롬프트   → --calc-scaffold
  2. self-consistency 다수결  → --samples N --temperature T (N>1이면 표본 다수결)
  3. tax-012 지식청크          → data/seeds/rag에 이미 추가됨(--rag로 on)
  4. 타임아웃 예산 증액        → --num-predict / --timeout

증분 jsonl append + 표준에러 로그(진실소스). 동시세션이 jsonl을 잘라도
로그로 복구/집계 가능. 같은 (qid, sample) 재실행 시 resume.

사용:
    # 실패군 12: 스캐폴드+self-consistency(temp0.6×3)+예산증액
    PYTHONPATH=scripts .venv/bin/python scripts/benchmark_levers.py \
        --ids-file /tmp/lever_fail.txt --rag data/seeds/rag --calc-scaffold \
        --samples 3 --temperature 0.6 --num-predict 20000 --num-ctx 28000 \
        --timeout 4000 --out docs/research/local-eval-runs/levers-fail.jsonl

    # 대조군 8: 스캐폴드 회귀검증(temp0 단일)
    PYTHONPATH=scripts .venv/bin/python scripts/benchmark_levers.py \
        --ids-file /tmp/lever_control.txt --rag data/seeds/rag --calc-scaffold \
        --samples 1 --temperature 0 --num-predict 16000 --num-ctx 24000 \
        --timeout 3000 --out docs/research/local-eval-runs/levers-control.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from benchmark_local import make_invoke  # PYTHONPATH=scripts 필요

from cpa_first.benchmark.runner import grade
from cpa_first.solver.solver import Solver, load_evaluation_questions


def _load_done(out: Path) -> set[tuple[str, int]]:
    done: set[tuple[str, int]] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
                done.add((r["question_id"], r["sample"]))
            except Exception:  # noqa: BLE001
                continue
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.5:27b-int4")
    ap.add_argument("--eval-dir", default="data/seeds/evaluation")
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--rag", default="")
    ap.add_argument("--calc-scaffold", action="store_true")
    ap.add_argument("--samples", type=int, default=1, help=">1이면 self-consistency 다수결")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--num-predict", type=int, default=16000)
    ap.add_argument("--num-ctx", type=int, default=24000)
    ap.add_argument("--timeout", type=int, default=3000)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ids = [ln.strip() for ln in Path(args.ids_file).read_text().splitlines() if ln.strip()]
    questions = load_evaluation_questions(args.eval_dir)
    qmap = {q["question_id"]: q for q in questions}
    questions = [qmap[i] for i in ids if i in qmap]

    rag_chunks: list = []
    if args.rag:
        from cpa_first.rag import load_chunks

        rag_chunks = load_chunks(Path(args.rag))
        print(f"[rag] {len(rag_chunks)} chunks from {args.rag}", file=sys.stderr)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = _load_done(out)
    print(
        f"[resume] {len(done)}건 완료. scaffold={args.calc_scaffold} "
        f"samples={args.samples} temp={args.temperature}",
        file=sys.stderr,
    )

    # 표본마다 동일 temperature. temp>0이면 ollama가 호출마다 다르게 샘플 → 다양성.
    solver = Solver(
        mode="live",
        model=args.model,
        invoke=make_invoke(
            args.model,
            temperature=args.temperature,
            num_predict=args.num_predict,
            num_ctx=args.num_ctx,
            timeout=args.timeout,
        ),
        rag_chunks=rag_chunks,
        calc_scaffold=args.calc_scaffold,
    )

    total = len(questions)
    t0 = time.monotonic()
    fout = out.open("a", encoding="utf-8")
    for qi, q in enumerate(questions, 1):
        qid = q["question_id"]
        for s in range(1, args.samples + 1):
            if (qid, s) in done:
                continue
            st = time.monotonic()
            try:
                res = solver.solve(q)
                chosen = res.chosen_index
                ok = grade(q, res).correct
            except Exception as exc:  # noqa: BLE001
                chosen, ok = -1, False
                print(f"  ERR {qid} s{s}: {exc}", file=sys.stderr, flush=True)
            dt = time.monotonic() - st
            rec = {
                "question_id": qid,
                "sample": s,
                "chosen": chosen,
                "correct_choice": q.get("correct_choice"),
                "ok": ok,
                "secs": round(dt, 1),
            }
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fout.flush()
            el = (time.monotonic() - t0) / 3600
            mark = "O" if ok else "X"
            print(
                f"[{qi}/{total}] {qid} s{s}/{args.samples} {mark} "
                f"chose={chosen} ans={q.get('correct_choice')} {dt:.0f}s (elapsed {el:.1f}h)",
                file=sys.stderr,
                flush=True,
            )
    fout.close()

    # 다수결 집계(로그가 아닌 jsonl 기준이되, 누락 시 부분집계 표시)
    by_q: dict[str, list[dict]] = {}
    for ln in out.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if r["question_id"] in set(ids):
            by_q.setdefault(r["question_id"], []).append(r)

    vote_correct = 0
    rows = []
    for qid in ids:
        recs = by_q.get(qid, [])
        if not recs:
            continue
        votes = [r["chosen"] for r in recs if r["chosen"] >= 0]
        ans = qmap[qid].get("correct_choice")
        if votes:
            winner = Counter(votes).most_common(1)[0][0]
        else:
            winner = -1
        mv_ok = winner == ans
        if mv_ok:
            vote_correct += 1
        rows.append(
            {
                "question_id": qid,
                "samples_done": len(recs),
                "votes": votes,
                "majority": winner,
                "ans": ans,
                "mv_ok": mv_ok,
            }
        )
    summary = {
        "model": args.model,
        "calc_scaffold": args.calc_scaffold,
        "samples": args.samples,
        "temperature": args.temperature,
        "num_predict": args.num_predict,
        "timeout": args.timeout,
        "n_questions": len(rows),
        "majority_vote_correct": vote_correct,
        "majority_vote_accuracy_pct": round(vote_correct / len(rows) * 100, 1) if rows else 0.0,
        "rows": rows,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    sm = out.with_suffix(".summary.json")
    sm.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n집계 저장: {sm}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
