#!/usr/bin/env python3
"""검증(정답 일치) 해설의 풀이 과정 품질을 LLM judge로 채점하는 배치 CLI.

대상: data/real_exams/cpa1/explanations/ 의 verified_answer_match 해설.
산출: data/real_exams/cpa1/judgments/<year>/<qid>.judgment.json + 요약 통계.

교차 채점 권장: 생성 백엔드와 다른 judge 백엔드를 쓴다 (자기 채점 편향 회피).
  # ollama 생성분을 codex로 채점
  .venv/bin/python scripts/judge_explanations.py --judge-backend codex --generated-by ollama
  # 전체 요약만 다시 출력
  .venv/bin/python scripts/judge_explanations.py --summary-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cpa_first.explain_gen.judge import run_judge_batch, summarize_judgments  # noqa: E402
from cpa_first.llm import make_invoke  # noqa: E402
from cpa_first.real_exams import (  # noqa: E402
    STATUS_VERIFIED,
    load_explanations,
    load_real_exam_questions,
)

REAL_EXAMS_DIR = ROOT / "data" / "real_exams" / "cpa1"
JUDGMENTS_DIR = REAL_EXAMS_DIR / "judgments"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge-backend", default="codex", help="codex|ollama|anthropic")
    parser.add_argument("--judge-model", default=None)
    parser.add_argument(
        "--generated-by", default="", help="이 문자열이 model에 포함된 해설만 채점 (예: ollama)"
    )
    parser.add_argument("--subjects", default="", help="쉼표 구분 과목 필터")
    parser.add_argument("--limit", type=int, default=0, help="최대 채점 건수 (0=무제한)")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--out", default=str(JUDGMENTS_DIR))
    args = parser.parse_args()

    if args.summary_only:
        print(json.dumps(summarize_judgments(args.out), ensure_ascii=False, indent=2))
        return 0

    questions = {q["question_id"]: q for q in load_real_exam_questions(REAL_EXAMS_DIR)}
    explanations = load_explanations(REAL_EXAMS_DIR / "explanations")
    subjects = {s.strip() for s in args.subjects.split(",") if s.strip()}

    pairs = []
    for qid, record in sorted(explanations.items()):
        if record.get("status") != STATUS_VERIFIED:
            continue
        if args.generated_by and args.generated_by not in str(record.get("model", "")):
            continue
        if subjects and record.get("subject") not in subjects:
            continue
        question = questions.get(qid)
        if question is None:
            continue
        pairs.append((record, question))
    if args.limit:
        pairs = pairs[: args.limit]
    if not pairs:
        print("채점 대상 0건", file=sys.stderr)
        return 1

    invoke = make_invoke(args.judge_backend, model=args.judge_model)
    label = f"{args.judge_backend}:{args.judge_model or 'default'}"
    print(f"채점 대상 {len(pairs)}건 (judge={label}) → {args.out}", flush=True)
    counts = run_judge_batch(
        pairs,
        invoke,
        args.out,
        judge_model_label=label,
        progress=lambda msg: print(msg, flush=True),
    )
    print(json.dumps(counts, ensure_ascii=False))
    print(json.dumps(summarize_judgments(args.out), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
