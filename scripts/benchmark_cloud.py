"""천장 돌파 테스트: 로컬 int4가 못 푼 잔존 오답을 클라우드(codex) 모델로 푼다.

같은 RAG 컨텍스트 + 같은 프롬프트(calc_scaffold)에서 모델만 교체한다.
codex가 풀면 → 병목은 지식/검색이 아니라 로컬 모델의 계산력임이 증명된다.
keyless(codex 자체 인증). 증분 jsonl + 로그(진실소스).

사용:
    .venv/bin/python scripts/benchmark_cloud.py --ids-file /tmp/still_wrong.txt \
        --rag data/seeds/rag --calc-scaffold --timeout 600 \
        --out docs/research/local-eval-runs/cloud-stillwrong.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from cpa_first.benchmark.runner import grade
from cpa_first.llm import codex_invoke
from cpa_first.solver.solver import Solver, load_evaluation_questions


def _load_done(out: Path) -> set[str]:
    done: set[str] = set()
    if out.exists():
        for ln in out.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                try:
                    done.add(json.loads(ln)["question_id"])
                except Exception:  # noqa: BLE001
                    pass
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids-file", required=True)
    ap.add_argument("--eval-dir", default="data/seeds/evaluation")
    ap.add_argument("--rag", default="")
    ap.add_argument("--calc-scaffold", action="store_true")
    ap.add_argument("--model", default="", help="codex -m 모델(미지정시 codex 기본)")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    ids = [ln.strip() for ln in Path(args.ids_file).read_text().splitlines() if ln.strip()]
    qmap = {q["question_id"]: q for q in load_evaluation_questions(args.eval_dir)}
    questions = [qmap[i] for i in ids if i in qmap]

    rag_chunks: list = []
    if args.rag:
        from cpa_first.rag import load_chunks

        rag_chunks = load_chunks(Path(args.rag))
        print(f"[rag] {len(rag_chunks)} chunks", file=sys.stderr)

    model = args.model or None

    def invoke(system: str, user: str) -> str:
        return codex_invoke(system, user, model=model, timeout=args.timeout)

    solver = Solver(
        mode="live",
        model=f"codex:{args.model or 'default'}",
        invoke=invoke,
        rag_chunks=rag_chunks,
        calc_scaffold=args.calc_scaffold,
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = _load_done(out)
    print(f"[resume] {len(done)}건 완료", file=sys.stderr)

    fout = out.open("a", encoding="utf-8")
    t0 = time.monotonic()
    correct = 0
    n = 0
    for i, q in enumerate(questions, 1):
        qid = q["question_id"]
        if qid in done:
            continue
        st = time.monotonic()
        try:
            res = solver.solve(q)
            chosen = res.chosen_index
            ok = grade(q, res).correct
        except Exception as exc:  # noqa: BLE001
            chosen, ok = -1, False
            print(f"  ERR {qid}: {exc}", file=sys.stderr, flush=True)
        dt = time.monotonic() - st
        n += 1
        if ok:
            correct += 1
        rec = {
            "question_id": qid,
            "chosen": chosen,
            "correct_choice": q.get("correct_choice"),
            "ok": ok,
            "secs": round(dt, 1),
        }
        fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fout.flush()
        mark = "O" if ok else "X"
        el = (time.monotonic() - t0) / 60
        print(
            f"[{i}/{len(questions)}] {qid} {mark} chose={chosen} "
            f"ans={q.get('correct_choice')} {dt:.0f}s (elapsed {el:.1f}m)",
            file=sys.stderr,
            flush=True,
        )
    fout.close()
    print(
        json.dumps(
            {"n": n, "correct": correct, "accuracy_pct": round(correct / n * 100, 1) if n else 0.0},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
