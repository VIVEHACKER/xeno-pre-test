"""비전 전사 결과를 math_lossy 경제 문항에 적용 → 복원된 평가셋 생성.

입력:
- data/real_exams/cpa1/parsed/<year>/economics.questions.json (정답키 보유, stem/보기 깨짐)
- /tmp/econ_vision.json + /tmp/econ_vision_2026fill.json (비전 전사 stem/보기)

처리: math_lossy 문항의 stem/choices를 비전 전사로 교체, correct_choice는 유지(이미 검증).
보기 5개 + stem 비어있지 않음 확인. review_status='vision_recovered'.

출력: data/real_exams/cpa1/parsed/<year>/economics.recovered.json (복원분만)

사용:
    .venv/bin/python scripts/apply_vision_recovery.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARSED = ROOT / "data" / "real_exams" / "cpa1" / "parsed"


def _load_vision() -> dict[str, dict[int, dict]]:
    """비전 전사 병합: 기본 + 2026 보충. {year: {number: {stem, choices, complete}}}."""
    base = json.loads(Path("/tmp/econ_vision.json").read_text(encoding="utf-8"))
    vision: dict[str, dict[int, dict]] = {
        y: {int(n): q for n, q in qs.items()} for y, qs in base.items()
    }
    fill_path = Path("/tmp/econ_vision_2026fill.json")
    if fill_path.exists():
        fill = json.loads(fill_path.read_text(encoding="utf-8"))
        vision.setdefault("2026", {})
        for n, q in fill.items():
            vision["2026"][int(n)] = q
    return vision


def main() -> int:
    vision = _load_vision()
    grand_recovered = grand_skipped = 0
    for year_dir in sorted(PARSED.glob("*")):
        year = year_dir.name
        src = year_dir / "economics.questions.json"
        if not src.exists():
            continue
        questions = json.loads(src.read_text(encoding="utf-8"))
        vis = vision.get(year, {})
        recovered = []
        skipped = []
        for q in questions:
            if not q.get("math_lossy"):
                continue
            num = int(q["question_id"][-3:])
            vq = vis.get(num)
            if vq is None or len(vq.get("choices") or []) != 5 or not vq.get("stem", "").strip():
                skipped.append(num)
                continue
            recovered.append(
                {
                    **q,
                    "stem": vq["stem"].strip(),
                    "choices": [c.strip() for c in vq["choices"]],
                    "math_lossy": False,
                    "review_status": "vision_recovered",
                    "recovery": {"method": "page_render+vision_transcribe", "dpi": 200},
                }
            )
        if recovered:
            out = year_dir / "economics.recovered.json"
            out.write_text(
                json.dumps(recovered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        grand_recovered += len(recovered)
        grand_skipped += len(skipped)
        print(f"[{year}] 복원 {len(recovered)} / 스킵 {skipped}")
    print(f"[done] 총 복원 {grand_recovered}, 스킵 {grand_skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
