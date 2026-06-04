"""로컬 LLM(ollama)으로 평가셋을 풀게 하고 실제 정답률을 측정한다.

solver.live 모드의 invoke 콜백에 ollama /api/chat 호출을 주입한다.
reasoned 모드와 달리 정답키 누수가 없다 — 모델이 실제로 푼 답만 채점한다.

사용:
    .venv/bin/python scripts/benchmark_local.py --model qwen3.5:27b-int4 --sample 12
    .venv/bin/python scripts/benchmark_local.py --model qwen3.5:27b-int4          # 전체 159
    # 세법만 RAG on, timeout 여유:
    .venv/bin/python scripts/benchmark_local.py --model qwen3.5:27b-int4 \\
        --ids-file /tmp/tax_all.txt --rag data/seeds/rag \\
        --num-predict 16000 --num-ctx 24000 --timeout 3000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

from cpa_first.benchmark.runner import grade
from cpa_first.solver.solver import _ANSWER_RE, Solver, load_evaluation_questions

OLLAMA_URL = "http://localhost:11434/api/chat"


def make_invoke(
    model: str,
    temperature: float = 0.0,
    timeout: int = 1800,
    num_predict: int = 8000,
    num_ctx: int = 16000,
):
    def invoke(system: str, user: str) -> str:
        options = {
            "temperature": temperature,
            "num_predict": num_predict,
        }
        # num_ctx 미설정 시 ollama 기본 컨텍스트가 작아 긴 num_predict가
        # 잘리거나 런너가 죽는다. 항상 명시한다.
        if num_ctx:
            options["num_ctx"] = num_ctx
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            # reasoning 모델은 thinking이 길어 기본 num_predict로는 답을 못 낸다.
            "options": options,
        }
        req = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        msg = data["message"]
        content = msg.get("content", "") or ""
        thinking = msg.get("thinking", "") or ""
        # 추출 우선순위: content의 ANSWER → 없으면 thinking의 *마지막* ANSWER.
        # (추론이 토큰 한도로 잘려 content가 미완성이어도 thinking 안의
        #  최종 결론 줄을 회수한다. 마지막 매치 = 가장 확정적 추론.)
        if _ANSWER_RE.search(content):
            return content
        matches = list(_ANSWER_RE.finditer(thinking))
        if matches:
            return f"{thinking}\nANSWER: {matches[-1].group(1)}"
        return content or thinking

    return invoke


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen3.5:27b-int4")
    ap.add_argument("--sample", type=int, default=0, help="0이면 전체")
    ap.add_argument("--eval-dir", default="data/seeds/evaluation")
    ap.add_argument("--out", default="")
    ap.add_argument("--ids", default="", help="쉼표구분 question_id만 채점")
    ap.add_argument("--ids-file", default="", help="줄단위 question_id 파일")
    ap.add_argument("--num-predict", type=int, default=8000)
    ap.add_argument("--num-ctx", type=int, default=16000)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument(
        "--rag",
        default="",
        help="RAG 청크 디렉터리(예: data/seeds/rag). 주면 open-book 측정.",
    )
    args = ap.parse_args()

    questions = load_evaluation_questions(args.eval_dir)
    id_filter: set[str] = set()
    if args.ids:
        id_filter |= {x.strip() for x in args.ids.split(",") if x.strip()}
    if args.ids_file:
        id_filter |= {
            ln.strip() for ln in Path(args.ids_file).read_text().splitlines() if ln.strip()
        }
    if id_filter:
        questions = [q for q in questions if q["question_id"] in id_filter]
    if args.sample > 0:
        # 과목 골고루 표본: subject별 round-robin
        by_subject: dict[str, list] = {}
        for q in questions:
            by_subject.setdefault(q["subject"], []).append(q)
        picked: list = []
        guard = 0
        while len(picked) < args.sample and any(by_subject.values()):
            for subj in list(by_subject):
                if by_subject[subj]:
                    picked.append(by_subject[subj].pop(0))
                    if len(picked) >= args.sample:
                        break
            guard += 1
            if guard > 1000:
                break
        questions = picked

    rag_chunks: list = []
    if args.rag:
        from cpa_first.rag import load_chunks

        rag_chunks = load_chunks(Path(args.rag))
        print(f"[rag] {len(rag_chunks)} chunks loaded from {args.rag}", file=sys.stderr)

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

    total = len(questions)
    correct = 0
    parsed = 0
    per_subject: dict[str, list[int]] = {}
    rows = []
    t0 = time.monotonic()
    for i, q in enumerate(questions, 1):
        qt0 = time.monotonic()
        try:
            res = solver.solve(q)
        except Exception as exc:  # noqa: BLE001
            print(
                f"[{i}/{total}] ERROR {q['question_id']}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            res = None
        dt = time.monotonic() - qt0
        if res is None:
            chosen = -1
            ok = False
        else:
            score = grade(q, res)
            chosen = res.chosen_index
            ok = score.correct
            if chosen >= 0:
                parsed += 1
        if ok:
            correct += 1
        subj = q["subject"]
        per_subject.setdefault(subj, [0, 0])
        per_subject[subj][1] += 1
        if ok:
            per_subject[subj][0] += 1
        rows.append(
            {
                "question_id": q["question_id"],
                "subject": subj,
                "chosen": chosen,
                "correct_choice": q.get("correct_choice"),
                "ok": ok,
                "secs": round(dt, 1),
            }
        )
        mark = "O" if ok else "X"
        print(
            f"[{i}/{total}] {mark} {q['question_id']:28s} "
            f"chose={chosen} ans={q.get('correct_choice')} {dt:.1f}s",
            file=sys.stderr,
            flush=True,
        )

    elapsed = time.monotonic() - t0
    summary = {
        "model": args.model,
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "answer_parse_rate": round(parsed / total, 4) if total else 0.0,
        "elapsed_secs": round(elapsed, 1),
        "avg_secs_per_q": round(elapsed / total, 1) if total else 0.0,
        "per_subject": {
            s: {
                "correct": c,
                "total": t,
                "accuracy": round(c / t, 4) if t else 0.0,
            }
            for s, (c, t) in per_subject.items()
        },
        "rows": rows,
    }

    out = (
        args.out
        or f"data/runtime/benchmark_runs/local-{args.model.replace(':', '_')}-{total}q.json"
    )
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(
        json.dumps(
            {k: v for k, v in summary.items() if k != "rows"},
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\n결과 저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
