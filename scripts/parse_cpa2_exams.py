#!/usr/bin/env python3
"""공인회계사 2차(주관식) 기출 PDF → 구조화 JSON 파서 (best-effort).

입력: scripts/collect_real_exams.py --phase 2 가 받은 공식 PDF (data/real_exams/cpa2/)
출력: data/real_exams/cpa2/parsed/<year>/<subject>.subjective.json

한계 (정직 표기):
- 금감원은 2차 모범답안·채점기준을 공개하지 않는다 → model_answer는 null.
- 2026년 PDF는 이미지 스캔본이라 텍스트 추출 불가 → 비전 복원(별도 단계) 전까지 스킵.
- 표/그림 손실 가능 → review_status='machine_parsed_raw'로 태깅, 원문 PDF 대조 전제.

구조: 2단 레이아웃 → 좌/우 컬럼 순서 복원 → 【문제 N】 경계 분할 → (물음 N) 추출.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "real_exams" / "cpa2"

# 파일명 키워드 → 과목 ID (재무회계1/2는 분권일 뿐 같은 과목).
SUBJECT_BY_KEYWORD = (
    ("세법", "tax"),
    ("재무관리", "financial_management"),
    ("회계감사", "audit"),
    ("원가관리회계", "cost_accounting"),
    ("원가회계", "cost_accounting"),
    ("재무회계", "financial_accounting"),
)

_PROBLEM_RE = re.compile(r"【\s*문\s*제\s*(\d+)\s*】\s*(?:\((\d+)점\))?")
_SUBQ_RE = re.compile(r"\(물음\s*(\d+)\)")


def subject_of(filename: str) -> str | None:
    for keyword, subject in SUBJECT_BY_KEYWORD:
        if keyword in filename:
            return subject
    return None


def page_columns(page: pdfplumber.page.Page) -> list[str]:
    """2단 레이아웃 페이지를 좌/우 컬럼 텍스트로 분리해 읽기 순서 복원."""
    mid = page.width / 2
    texts: list[str] = []
    for box in ((0, 0, mid, page.height), (mid, 0, page.width, page.height)):
        cropped = page.crop(box)
        texts.append(cropped.extract_text() or "")
    return texts


def extract_full_text(pdf_path: Path) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        parts: list[str] = []
        for page in pdf.pages:
            parts.extend(page_columns(page))
        return "\n".join(parts)


def split_problems(text: str) -> list[dict]:
    """【문제 N】 경계로 분할. 마커 이전 프리앰블(답안 유의사항)은 버린다."""
    markers = list(_PROBLEM_RE.finditer(text))
    problems: list[dict] = []
    for i, m in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        body = text[m.end() : end].strip()
        sub_questions = [
            f"(물음 {sm.group(1)})"
            + body[sm.end() : _next_subq_start(body, sm.end())].strip()[:2000]
            for sm in _SUBQ_RE.finditer(body)
        ]
        problems.append(
            {
                "number": int(m.group(1)),
                "points": int(m.group(2)) if m.group(2) else None,
                "stem": body,
                "sub_questions": sub_questions,
            }
        )
    return problems


def _next_subq_start(body: str, pos: int) -> int:
    nxt = _SUBQ_RE.search(body, pos)
    return nxt.start() if nxt else len(body)


def parse_year(year_dir: Path, out_dir: Path) -> dict[str, int]:
    year = int(year_dir.name)
    by_subject: dict[str, list[dict]] = {}
    skipped_scanned = 0
    for pdf_path in sorted(year_dir.glob("*.pdf")):
        subject = subject_of(pdf_path.name)
        if subject is None:
            continue
        text = extract_full_text(pdf_path)
        # 스캔본 감지: 페이지당 평균 추출량이 극히 적으면 텍스트 레이어 부재.
        if len(text.strip()) < 500:
            print(f"  [skip] {pdf_path.name} — 스캔본(텍스트 레이어 없음), 비전 복원 대상")
            skipped_scanned += 1
            continue
        problems = split_problems(text)
        if not problems:
            print(f"  [warn] {pdf_path.name} — 【문제 N】 마커 미검출", file=sys.stderr)
            continue
        bucket = by_subject.setdefault(subject, [])
        for p in problems:
            bucket.append({**p, "source_file": pdf_path.name})

    counts: dict[str, int] = {}
    for subject, problems in by_subject.items():
        problems.sort(key=lambda p: (p["source_file"], p["number"]))
        records = [
            {
                "question_id": f"cpa2-real-{year}-{subject}-q{i:02d}",
                "exam": "CPA_2",
                "subject": subject,
                "applicable_year": year,
                "number": p["number"],
                "points": p["points"],
                "stem": p["stem"],
                "sub_questions": p["sub_questions"],
                "model_answer": None,
                "grading_criteria": None,
                "answer_key_policy": "모범답안·채점기준 비공개(금감원 정책)",
                "review_status": "machine_parsed_raw",
                "rights_status": "official_download_check_required",
                "source": p["source_file"],
            }
            for i, p in enumerate(problems, start=1)
        ]
        out_path = out_dir / str(year) / f"{subject}.subjective.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        counts[subject] = len(records)
    if skipped_scanned:
        counts["_skipped_scanned_pdfs"] = skipped_scanned
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--years", default="", help="쉼표구분 연도 (기본: 전부)")
    args = ap.parse_args()
    years = {int(y) for y in args.years.split(",") if y.strip()}

    out_dir = RAW_DIR / "parsed"
    total = 0
    for year_dir in sorted(p for p in RAW_DIR.iterdir() if p.is_dir() and p.name.isdigit()):
        if years and int(year_dir.name) not in years:
            continue
        print(f"[{year_dir.name}]")
        counts = parse_year(year_dir, out_dir)
        print(f"  → {counts}")
        total += sum(v for k, v in counts.items() if not k.startswith("_"))
    print(f"[done] 총 {total}문제")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
