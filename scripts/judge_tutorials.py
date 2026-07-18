#!/usr/bin/env python3
"""exam_core 튜토리얼 사실 정확성 채점 배치 CLI (전문가 검수 큐 생성).

대상: data/seeds/subject_tutorials_exam_core.json 의 48개 튜토리얼.
산출: data/seeds/subject_tutorials_exam_core.judgments/<tutorial_id>.tutorial_judgment.json
      + 검수 우선순위로 정렬된 요약.

교차 채점 권장: 생성 모델(claude-fable-5)과 다른 judge 백엔드 사용.
  # codex로 채점 (느리지만 독립적)
  .venv/bin/python scripts/judge_tutorials.py --judge-backend codex
  # 요약만 다시 출력
  .venv/bin/python scripts/judge_tutorials.py --summary-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cpa_first.explain_gen.tutorial_judge import (  # noqa: E402
    run_tutorial_judge_batch,
    summarize_tutorial_judgments,
)
from cpa_first.llm import make_invoke  # noqa: E402

TUTORIALS_PATH = ROOT / "data" / "seeds" / "subject_tutorials_exam_core.json"
JUDGMENTS_DIR = ROOT / "data" / "seeds" / "subject_tutorials_exam_core.judgments"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judge-backend", default="codex", help="codex|ollama|anthropic")
    parser.add_argument("--judge-model", default=None)
    parser.add_argument(
        "--subjects", default="", help="쉼표구분 subject_id 필터 (예: cpa1_accounting)"
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--out", default=str(JUDGMENTS_DIR))
    args = parser.parse_args()

    if args.summary_only:
        print(json.dumps(summarize_tutorial_judgments(args.out), ensure_ascii=False, indent=2))
        return 0

    tutorials = json.loads(TUTORIALS_PATH.read_text(encoding="utf-8"))["tutorials"]
    subjects = {s.strip() for s in args.subjects.split(",") if s.strip()}
    if subjects:
        tutorials = [t for t in tutorials if t.get("subject_id") in subjects]
    if args.limit:
        tutorials = tutorials[: args.limit]
    if not tutorials:
        print("채점 대상 0건", file=sys.stderr)
        return 1

    invoke = make_invoke(args.judge_backend, model=args.judge_model)
    label = f"{args.judge_backend}:{args.judge_model or 'default'}"
    print(f"채점 대상 {len(tutorials)}개 (judge={label}) → {args.out}", flush=True)
    counts = run_tutorial_judge_batch(
        tutorials,
        invoke,
        args.out,
        judge_model_label=label,
        progress=lambda msg: print(msg, flush=True),
    )
    print(json.dumps(counts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
