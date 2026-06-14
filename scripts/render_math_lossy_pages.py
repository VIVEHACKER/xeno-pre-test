"""math_lossy 문항(주로 경제 수식)이 있는 페이지를 PNG로 렌더 + 문항↔페이지 매핑.

PDF 수식 폰트에 ToUnicode가 없어 텍스트 추출 시 PUA 글리프로 유실되는 문항을,
페이지 이미지로 렌더해 비전 모델이 전사할 수 있게 한다(텍스트 파이프라인 한계 우회).

출력:
- data/real_exams/cpa1/vision/<year>/<subject>_p<NN>.png  (렌더 이미지, gitignore)
- data/real_exams/cpa1/vision/<year>/<subject>.page_map.json  ({문항번호: 페이지번호})

사용:
    .venv/bin/python scripts/render_math_lossy_pages.py --subject economics
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "real_exams" / "cpa1"
sys.path.insert(0, str(ROOT / "scripts"))
from parse_real_exams import (  # noqa: E402
    QUESTION_FILES,
    _page_subject,
    _resolve_pdf,
)

_Q_NUM = re.compile(r"(?m)^\s*(\d{1,2})\.(?!\d)")


def _math_lossy_numbers(year: int, subject: str) -> list[int]:
    path = RAW_DIR / "parsed" / str(year) / f"{subject}.questions.json"
    if not path.exists():
        return []
    return [
        int(q["question_id"][-3:])
        for q in json.loads(path.read_text(encoding="utf-8"))
        if q.get("math_lossy")
    ]


def _source_pdf(year: int, subject: str) -> Path | None:
    for filename, subjects in QUESTION_FILES[year]:
        if subject in subjects:
            return _resolve_pdf(RAW_DIR / str(year) / filename)
    return None


def _question_pages(pdf_path: Path, subject: str) -> tuple[dict[int, int], list[int]]:
    """({문항번호: 1-기반 페이지번호}, 과목 전체 페이지 목록).

    과목 헤더로 현재 과목을 추적. 문항 시작 줄이 수식 유실로 탐지 안 되는 경우가
    있어 page_of는 불완전할 수 있다 — 따라서 과목 '전체 페이지'도 함께 반환해
    누락 문항이 인접 페이지에서 빠지지 않게 한다.
    """
    page_of: dict[int, int] = {}
    subject_pages: list[int] = []
    current = None
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            detected = _page_subject(text)
            if detected is not None:
                current = detected
            if current != subject:
                continue
            subject_pages.append(page_no)
            for m in _Q_NUM.finditer(text):
                num = int(m.group(1))
                if num not in page_of:
                    page_of[num] = page_no
    return page_of, subject_pages


def _render(pdf_path: Path, page_no: int, out_png: Path, dpi: int = 200) -> None:
    out_png.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["mutool", "draw", "-o", str(out_png), "-r", str(dpi), str(pdf_path), str(page_no)],
        check=True,
        capture_output=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subject", default="economics")
    ap.add_argument("--years", default="", help="쉼표구분 (기본: 전부)")
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()

    years = [int(y) for y in args.years.split(",") if y.strip()] or sorted(QUESTION_FILES)
    out_base = RAW_DIR / "vision"

    for year in years:
        lossy = _math_lossy_numbers(year, args.subject)
        if not lossy:
            print(f"[{year}/{args.subject}] math_lossy 없음")
            continue
        pdf_path = _source_pdf(year, args.subject)
        if pdf_path is None or not pdf_path.exists():
            print(f"[{year}/{args.subject}] 소스 PDF 없음", file=sys.stderr)
            continue
        page_of, subject_pages = _question_pages(pdf_path, args.subject)
        # 과목 전체 페이지를 렌더 — 시작 줄 미탐지 문항도 인접 페이지에 포함되게.
        pages = sorted(set(subject_pages))
        page_map = {n: page_of[n] for n in lossy if n in page_of}
        for page_no in pages:
            out_png = out_base / str(year) / f"{args.subject}_p{page_no:02d}.png"
            _render(pdf_path, page_no, out_png, args.dpi)
        map_path = out_base / str(year) / f"{args.subject}.page_map.json"
        map_path.write_text(
            json.dumps(
                {"page_of_question": page_map, "subject_pages": pages, "math_lossy": lossy},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        missing = [n for n in lossy if n not in page_of]
        print(
            f"[{year}/{args.subject}] math_lossy {len(lossy)} → 과목 페이지 {len(pages)}개 전체 렌더"
            f" (시작줄 매핑 {len(page_map)}, 미탐지 {missing} — 인접 페이지에 포함)"
        )
    print(f"[done] 렌더 → {out_base}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
