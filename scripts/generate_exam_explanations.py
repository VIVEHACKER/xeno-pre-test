#!/usr/bin/env python3
"""실기출 597문항 AI 해설 배치 생성 CLI.

blind solve → 정답키 대조 → data/real_exams/cpa1/explanations/<year>/<qid>.explanation.json
파일 존재 = 완료 체크포인트: 중단돼도 같은 명령을 다시 실행하면 이어서 돈다.

사용 예:
  # 로컬 ollama로 2026년 전 과목 (무료·오프라인, ~1분/문항)
  .venv/bin/python scripts/generate_exam_explanations.py \
      --years 2026 --backend ollama --model qwen3.5:27b-int4

  # codex로 세법만 (느리지만 계산형 정확도 최고 실측)
  .venv/bin/python scripts/generate_exam_explanations.py \
      --years 2026 --subjects tax --backend codex

  # 과목별 라우팅 (routing solver): 세법=codex, 나머지=ollama
  CPA_LLM_ROUTES="tax=codex,*=ollama" CPA_LLM_MODEL=qwen3.5:27b-int4 \
      .venv/bin/python scripts/generate_exam_explanations.py --years 2026 --routed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cpa_first.explain_gen import run_batch  # noqa: E402
from cpa_first.real_exams import load_real_exam_questions  # noqa: E402
from cpa_first.solver import create_solver  # noqa: E402

REAL_EXAMS_DIR = ROOT / "data" / "real_exams" / "cpa1"
RAG_DIR = ROOT / "data" / "seeds" / "rag"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", default="", help="쉼표 구분 연도 (기본: 전체)")
    parser.add_argument("--subjects", default="", help="쉼표 구분 과목 (기본: 전체)")
    parser.add_argument("--backend", default="ollama", help="ollama|codex|anthropic")
    parser.add_argument("--model", default=None, help="백엔드 모델명")
    parser.add_argument(
        "--routed", action="store_true", help="CPA_LLM_ROUTES 환경변수 기반 과목별 라우팅"
    )
    parser.add_argument("--limit", type=int, default=0, help="최대 문항 수 (0=무제한)")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--no-skip", action="store_true", help="기존 파일도 다시 생성")
    parser.add_argument("--out", default=str(REAL_EXAMS_DIR / "explanations"))
    args = parser.parse_args()

    years = [int(y) for y in args.years.split(",") if y.strip()] or None
    subjects = [s.strip() for s in args.subjects.split(",") if s.strip()] or None

    questions = load_real_exam_questions(REAL_EXAMS_DIR, years=years, subjects=subjects)
    if not questions:
        print("문항 0건 — --years/--subjects 확인", file=sys.stderr)
        return 1
    if args.limit:
        questions = questions[: args.limit]

    if args.routed:
        solver = create_solver(mode="live", rag_dir=RAG_DIR)
    else:
        solver = create_solver(mode="live", backend=args.backend, model=args.model, rag_dir=RAG_DIR)

    print(f"대상 {len(questions)}문항 → {args.out}", flush=True)
    counts = run_batch(
        questions,
        solver,
        args.out,
        skip_existing=not args.no_skip,
        max_attempts=args.max_attempts,
        progress=lambda msg: print(msg, flush=True),
    )
    print(json.dumps(counts, ensure_ascii=False))
    # verified가 하나도 없으면 실패로 간주 (전량 스킵은 성공).
    generated = sum(v for k, v in counts.items() if k != "skipped_existing")
    if generated and not counts.get("verified_answer_match"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
