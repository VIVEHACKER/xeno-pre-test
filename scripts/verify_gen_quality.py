"""문제 제작 능력 검증 드라이버 — 소규모 생성 + 독립 모델 교차검증 실측.

생성/검토: codex, 정답키 교차검증: ollama(진짜 독립 모델).
산출물은 임시 디렉터리에 쓰고 data/seeds/는 건드리지 않는다.

사용:
    CPA_OLLAMA_MODEL=qwen3.5:27b-int4 .venv/bin/python scripts/verify_gen_quality.py \\
        --target-dir /tmp/gen-verify
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from generate_eval_set import GenItem, run_plan  # noqa: E402

from cpa_first.llm import make_invoke  # noqa: E402

VERIFY_PLAN = [
    GenItem("accounting", "cvp", "mid", 1),
    GenItem("business", "financial_management", "easy", 1),
    GenItem("tax", "corporate_tax", "hard", 1),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-dir", type=Path, default=Path("/tmp/gen-verify"))
    ap.add_argument("--gen-backend", default="codex")
    ap.add_argument("--cross-check-backend", default="ollama")
    args = ap.parse_args()

    args.target_dir.mkdir(parents=True, exist_ok=True)
    invoke = make_invoke(args.gen_backend)
    cross_check_invoke = make_invoke(args.cross_check_backend)

    result = run_plan(
        VERIFY_PLAN,
        invoke,
        args.target_dir,
        cross_check_invoke=cross_check_invoke,
    )
    summary = {
        "plan_items": len(VERIFY_PLAN),
        "stats": result["stats"],
        "verdicts": result["verdicts"],
        "written_files": [p.name for p in result["written"]],
        "gen_backend": args.gen_backend,
        "cross_check_backend": args.cross_check_backend,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    (args.target_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
