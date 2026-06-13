"""공인회계사 1차 실기출 PDF → 구조화 JSON 파서.

입력: scripts/collect_real_exams.py가 받은 공식 PDF (data/real_exams/cpa1/)
출력: data/real_exams/cpa1/parsed/<year>/<subject>.questions.json (gitignore — eval 전용)

설계:
- 문제지는 2단 레이아웃 → 페이지를 좌/우 컬럼으로 crop해 읽기 순서 복원.
- 문항 경계: 줄 시작 "N." (1~50). 보기 경계: ①②③④⑤.
- 정답: 정답 PDF의 과목별 표에서 ①형 컬럼 → 0-기반 인덱스.
- 표/그림이 있던 문항은 텍스트 추출이 손실될 수 있어 table_lossy 플래그를 단다
  (벤치마크에서 분리 보고).

권리: 공식 출처 eval 전용. RAG/학습 투입 금지(train_after_rights_review).

사용:
    .venv/bin/python scripts/parse_real_exams.py --year 2024 --subjects corporate_law,tax
    .venv/bin/python scripts/parse_real_exams.py            # 등록된 전부
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "real_exams" / "cpa1"

CIRCLED = "①②③④⑤"


def _resolve_pdf(path: Path) -> Path:
    """손상 원본을 qpdf/mutool로 복구한 .norm.pdf가 있으면 우선 사용.

    2026년 공식 PDF는 xref 스트림이 잘린 채 서빙된다(재다운로드 동일) —
    pdfminer가 못 읽어 복구본을 만들어 둔다. 원본은 provenance용으로 보존.
    """
    norm = path.with_name(path.stem + ".norm.pdf")
    return norm if norm.exists() else path


# 점 뒤 공백을 요구하지 않는다 — 세법 문항은 `1.「국세기본법」`처럼 붙는다.
# (?!\d)로 소수(1.5)는 배제.
_Q_START = re.compile(r"(?m)^\s*(\d{1,2})\.(?!\d)")
_CHOICE_SPLIT = re.compile(r"(?=[①②③④⑤])")

# 과목 표준 ID 매핑 (정답 PDF 페이지 헤더 / 문제지 헤더의 과목명 기준)
SUBJECT_BY_HEADER = {
    "경영학": "business",
    "경제원론": "economics",
    "상법": "corporate_law",
    "기업법": "corporate_law",  # 2025+ 과목명 개편
    "세법": "tax",
    "세법개론": "tax",
    "회계학": "accounting",
}

# 연도별 문제지 파일 → 담긴 과목 순서 (페이지 헤더로 재확인)
QUESTION_FILES = {
    2024: [
        ("_01.경영학(1형)문제_2024.pdf", ["business"]),
        ("_01.경제원론(1형)문제_2024.pdf", ["economics"]),
        ("_02.상법(1형)문제_2024.pdf", ["corporate_law"]),
        ("_02.세법(1형)문제_2024.pdf", ["tax"]),
        ("_03.회계학(1형)문제_2024.pdf", ["accounting"]),
    ],
    2025: [
        ("1교시 경영학 경제원론(1형)_문제_2025.pdf", ["business", "economics"]),
        ("2교시 기업법 세법개론(1형)_문제_2025.pdf", ["corporate_law", "tax"]),
        ("3교시 회계학(1형)_문제_2025.pdf", ["accounting"]),
    ],
    2026: [
        ("1교시 경영학 경제원론(1형)_문제(최종)_2026.pdf", ["business", "economics"]),
        ("2교시 기업법 세법개론(1형)_문제(최종)_2026.pdf", ["corporate_law", "tax"]),
        ("3교시 회계학(1형)_문제(최종)_2026.pdf", ["accounting"]),
    ],
}

ANSWER_FILES = {
    2024: "정답_2024.pdf",
    2025: "정답_2025.pdf",
    2026: "최종정답확정_2026.pdf",
}


# 헤더(과목명·교시·페이지, y≤100)와 푸터('(계속)'·페이지번호, 하단 60pt)는 본문이 아니다 —
# crop으로 원천 배제한다(실측: 본문은 y 110~970 사이, 푸터 혼입이 보기⑤ 오염의 주범이었음).
_HEADER_MARGIN = 100
_FOOTER_MARGIN = 60

# crop이 놓친 잔여 노이즈 줄(과목명 조각·교시·계속 표시 등) — 단독 줄일 때만 제거.
_NOISE_LINE = re.compile(
    r"(?m)^\s*("
    r"\d+/\d+|\d{1,3}|"  # 페이지 번호 (N/16 또는 단독 숫자)
    r"상법|기업법?|업법|경영학?|영학|경제원론?|원론|회계학?|계학|세법(개론?)?|법개론|법|"
    r"제\d교시|\(계속\)|[①②]형|책형|-끝-|책형을 다시 한 번 확인하십시오\.?"
    r")\s*$\n?"
)


def _column_split(page: pdfplumber.page.Page, words: list[dict]) -> float:
    """단어가 걸치지 않는 컬럼 분할선을 페이지별로 찾는다.

    고정 중앙선(width/2)은 위험하다 — 2026 기업법은 우측 컬럼 문항번호가
    x=361에서 시작해 중앙선(364.5)을 침범, 좌측 컬럼 stem에 숫자가 섞였다.
    폭 42~58% 범위에서 단어 교차가 최소인 x를 고른다(동률이면 중앙에 가까운 쪽).
    """
    center = page.width / 2
    best_x, best_score = center, None
    for x in range(int(page.width * 0.42), int(page.width * 0.58), 2):
        crossings = sum(1 for w in words if w["x0"] < x < w["x1"])
        score = (crossings, abs(x - center))
        if best_score is None or score < best_score:
            best_x, best_score = float(x), score
    return best_x


def _page_columns(page: pdfplumber.page.Page) -> list[str]:
    """2단 레이아웃 페이지 → [좌컬럼 텍스트, 우컬럼 텍스트].

    헤더/푸터 영역과 경계 걸침 객체는 within_bbox(완전 포함)로 배제한다 —
    crop(교차 포함)은 헤더/푸터 경계에 걸친 페이지 번호('10/16')를 끌고 들어온다.
    """
    words = page.extract_words()
    split = _column_split(page, words)
    top = min(_HEADER_MARGIN, page.height / 4)
    bottom = max(page.height - _FOOTER_MARGIN, page.height * 3 / 4)
    texts: list[str] = []
    for box in ((0, top, split, bottom), (split, top, page.width, bottom)):
        col = page.within_bbox(box)
        texts.append(_NOISE_LINE.sub("", col.extract_text() or ""))
    return texts


def _page_subject(page_text: str) -> str | None:
    """페이지 첫 줄들에서 과목 헤더 탐지."""
    head = page_text[:80]
    for name, subject in SUBJECT_BY_HEADER.items():
        if name in head:
            return subject
    return None


def _page_has_table(page: pdfplumber.page.Page) -> bool:
    try:
        return bool(page.find_tables())
    except Exception:  # noqa: BLE001 — 표 탐지 실패는 플래그 불가로만 처리
        return False


def extract_questions(pdf_path: Path, expected_subjects: list[str]) -> dict[str, list[dict]]:
    """문제지 PDF → {subject: [{"number", "stem", "choices", "table_lossy"}]}.

    컬럼 텍스트를 과목별로 이어붙인 뒤 문항 번호로 분할한다. 과목 전환은
    페이지 헤더로 감지하고, 못 찾으면 직전 과목을 유지한다.
    """
    by_subject: dict[str, list[str]] = {s: [] for s in expected_subjects}
    lossy_pages: dict[str, set[int]] = {s: set() for s in expected_subjects}
    current = expected_subjects[0]

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            full_text = page.extract_text() or ""
            detected = _page_subject(full_text)
            if detected in by_subject:
                current = detected
            cols = _page_columns(page)
            by_subject[current].extend(cols)
            if _page_has_table(page):
                lossy_pages[current].add(page_no)

    out: dict[str, list[dict]] = {}
    for subject, chunks in by_subject.items():
        text = "\n".join(chunks)
        questions = _split_questions(text)
        has_table_pages = bool(lossy_pages[subject])
        for q in questions:
            # 과목 단위 표 존재는 근사 신호 — 문항 단위 정밀 매핑은 하지 않는다(정직 플래그).
            q["table_lossy"] = has_table_pages and _looks_tabular(q["stem"])
            # 수식 폰트에 ToUnicode 매핑이 없으면 수식이 PUA 글리프로 유실된다
            # (경제원론 실측 64%) — 텍스트 복원 불가이므로 벤치마크에서 제외 대상.
            q["math_lossy"] = bool(
                _PUA_RE.search(q["stem"]) or any(_PUA_RE.search(c) for c in q["choices"])
            )
        out[subject] = questions
    return out


def _looks_tabular(stem: str) -> bool:
    """표 손실 가능성 휴리스틱: 숫자 나열/자료 표제가 있는 계산형 문항."""
    signals = ("다음 자료", "다음과 같다", "(주)", "원)", "₩")
    return any(s in stem for s in signals)


_PUA_RE = re.compile("[\ue000-\uf8ff]")  # Private Use Area — ToUnicode 매핑 없는 수식 글리프
# "※ 다음 자료를 이용하여 31번과 32번에 답하시오." — 두 문항이 공유하는 자료 블록.
_SHARED_BLOCK_HEAD = re.compile(r"※[^\n①②③④⑤]{0,60}?(\d{1,2})번과\s*(\d{1,2})번에\s*답하시오")


def _extract_shared_blocks(text: str) -> tuple[str, dict[int, str]]:
    """공유 자료 블록(※ N번과 M번에 답하시오 ... 자료)을 분리한다.

    블록은 ※ 표제부터 N번 문항 시작 직전까지. 분리하지 않으면 직전 문항의
    보기⑤ 꼬리에 붙거나 통째로 유실된다(회계 실측 — 연도당 1블록 2문항).
    반환: (블록 제거된 텍스트, {문항번호: 블록 텍스트}).
    """
    blocks: dict[int, str] = {}
    while True:
        m = _SHARED_BLOCK_HEAD.search(text)
        if m is None:
            return text, blocks
        n1, n2 = int(m.group(1)), int(m.group(2))
        q_start = re.compile(rf"(?m)^\s*{n1}\.(?!\d)").search(text, m.end())
        end = q_start.start() if q_start else m.end()
        block = text[m.start() : end].strip()
        blocks[n1] = block
        blocks[n2] = block
        # 개행 패딩 — 블록 제거 후 앞뒤가 붙어 n1번 문항 시작('^N.')의 줄 앵커가
        # 깨지면 해당 문항이 통째로 drop된다(코드리뷰 적발).
        text = text[: m.start()] + "\n" + text[end:]


def _exam_note(preamble: str) -> str:
    """문항 1 이전의 ※ 전역 전제(예: 조세부담 최소화 가정)를 추출.

    '보기 중에서 ... 고르시오' 보일러플레이트는 제외 — 전 과목 공통 문구라 정보가 없다.
    """
    notes = []
    for chunk in re.split(r"(?=※)", preamble):
        chunk = chunk.strip()
        if chunk.startswith("※") and "고르시오" not in chunk and len(chunk) > 5:
            notes.append(chunk.lstrip("※ ").strip())
    return " / ".join(notes)


def _split_questions(text: str) -> list[dict]:
    """과목 텍스트 → 문항 리스트.

    - 문항 번호는 1부터 증가, 시작 줄 유실 대비 최대 +3 갭 허용.
    - 공유 자료 블록은 해당 두 문항 stem 앞에 복원.
    - 전역 ※ 전제는 모든 문항 stem 앞에 "(전제: ...)"로 주입 — 풀이 조건이므로.
    """
    text, shared_blocks = _extract_shared_blocks(text)
    starts = [(m.start(), int(m.group(1))) for m in _Q_START.finditer(text)]
    filtered: list[tuple[int, int]] = []
    expect = 1
    for pos, num in starts:
        if num == expect:
            filtered.append((pos, num))
            expect = num + 1
        elif expect < num <= expect + 3:
            # 직전 문항 시작이 유실된 갭 — 본문 오탐 방지 위해 작은 점프만 허용
            filtered.append((pos, num))
            expect = num + 1
    note = _exam_note(text[: filtered[0][0]]) if filtered else ""
    questions: list[dict] = []
    for i, (pos, num) in enumerate(filtered):
        end = filtered[i + 1][0] if i + 1 < len(filtered) else len(text)
        block = text[pos:end]
        parts = _CHOICE_SPLIT.split(block)
        # 보기는 항상 블록의 '마지막' ①~⑤ 다섯 개다 — 세법 계산형은 stem의 자료
        # 목록도 ①~⑤ 번호를 써서(실측 13문항) 앞에서 5개를 집으면 자료를 보기로
        # 오인하고 진짜 보기를 버린다. 마지막 5개가 ①②③④⑤ 순서일 때만 채택.
        overflow = len(parts) > 6
        if len(parts) >= 6 and [p[0] for p in parts[-5:]] == list(CIRCLED):
            stem_text = "".join(parts[:-5])
            choice_parts = parts[-5:]
        else:
            stem_text = parts[0]
            choice_parts = parts[1:6]
        stem = _Q_START.sub("", stem_text, count=1).strip()
        if num in shared_blocks:
            stem = f"{shared_blocks[num]}\n{stem}"
        if note:
            stem = f"(전제: {note})\n{stem}"
        choices = [p[1:].strip().rstrip("※").strip() for p in choice_parts if p]
        questions.append(
            {
                "number": num,
                "stem": stem,
                "choices": choices,
                # stem에 ①~⑤ 자료 번호가 있었음(마지막-5 규칙으로 처리됨) — 검수 표시.
                "split_overflow": overflow,
            }
        )
    return questions


def _answer_index(token: str) -> int | None:
    """정답 토큰 → 0-기반 인덱스. 연도에 따라 ①~⑤ 또는 1~5 표기."""
    token = token.strip()
    if token in CIRCLED:
        return CIRCLED.index(token)
    if token.isdigit() and 1 <= int(token) <= 5:
        return int(token) - 1
    return None


# 정답표 줄: "문항번호 ①형값 ②형값". group(2)=①형(첫 정답값)을 채택한다 —
# 공식 정답 PDF는 전 연도 '문항번호 ①형 ②형' 순서 고정(파싱 검증으로 4과목 254/254
# 정답 일치 확증). group(3)을 명시해 ②형 위치를 분명히 한다(코드리뷰 명료화).
_ANSWER_LINE = re.compile(r"(\d{1,2})\s+([①②③④⑤1-5])\s+([①②③④⑤1-5])")


def extract_answers(pdf_path: Path) -> dict[str, dict[int, int]]:
    """정답 PDF → {subject: {문항번호: 0-기반 정답 인덱스}} (①형 기준).

    1차: 표 추출(행 패턴 [문항번호, ①형, ②형, 문항번호, ①형, ②형]).
    2차: 표 셀이 비는 경우가 있어 텍스트 줄("1 ⑤ ① 21 ③ ③")로 누락분 보충.
    """
    out: dict[str, dict[int, int]] = {}
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            subject = _page_subject(text)
            if subject is None:
                continue
            answers = out.setdefault(subject, {})
            for table in page.extract_tables():
                for row in table:
                    cells = [c.strip() if isinstance(c, str) else c for c in row]
                    for base in range(0, len(cells) - 1, 3):
                        num, first = cells[base], cells[base + 1]
                        if not (num and first and num.isdigit()):
                            continue
                        idx = _answer_index(first)
                        if idx is not None:
                            answers[int(num)] = idx
            # 텍스트 줄 폴백 — 표 파싱이 놓친 문항만 채운다
            for m in _ANSWER_LINE.finditer(text):
                num, first = int(m.group(1)), m.group(2)
                if num not in answers:
                    idx = _answer_index(first)
                    if idx is not None:
                        answers[num] = idx
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=0, help="0이면 전부")
    ap.add_argument("--subjects", default="", help="쉼표구분 과목 ID (기본: 전부)")
    ap.add_argument("--out-dir", type=Path, default=RAW_DIR / "parsed")
    args = ap.parse_args()

    years = [args.year] if args.year else sorted(QUESTION_FILES)
    want_subjects = {s.strip() for s in args.subjects.split(",") if s.strip()}

    total_ok = 0
    for year in years:
        answer_path = _resolve_pdf(RAW_DIR / str(year) / ANSWER_FILES[year])
        answers = extract_answers(answer_path)
        for filename, subjects in QUESTION_FILES[year]:
            if want_subjects and not (set(subjects) & want_subjects):
                continue
            pdf_path = _resolve_pdf(RAW_DIR / str(year) / filename)
            if not pdf_path.exists():
                print(f"[{year}] 없음: {filename}", file=sys.stderr)
                continue
            parsed = extract_questions(pdf_path, subjects)
            for subject, questions in parsed.items():
                if want_subjects and subject not in want_subjects:
                    continue
                subject_answers = answers.get(subject, {})
                records, issues = [], []
                for q in questions:
                    issue = None
                    if len(q["choices"]) != 5:
                        issue = f"choices={len(q['choices'])}"
                    elif q["number"] not in subject_answers:
                        issue = "정답 없음"
                    elif len(q["stem"]) < 10:
                        issue = "stem 과소"
                    if issue:
                        issues.append(f"Q{q['number']}: {issue}")
                        continue
                    records.append(
                        {
                            "question_id": f"cpa1-real-{year}-{subject}-{q['number']:03d}",
                            "exam": "CPA_1",
                            "subject": subject,
                            "unit": None,
                            "applicable_year": year,
                            "stem": q["stem"],
                            "choices": q["choices"],
                            "correct_choice": subject_answers[q["number"]],
                            "table_lossy": q["table_lossy"],
                            "math_lossy": q["math_lossy"],
                            "split_overflow": q.get("split_overflow", False),
                            "rights_status": "official_public_eval_only",
                            "review_status": "parsed_unverified",
                            "source": {
                                "owner": "금융감독원",
                                "file": filename,
                                "answer_file": ANSWER_FILES[year],
                            },
                        }
                    )
                out_path = args.out_dir / str(year) / f"{subject}.questions.json"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(
                    json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                lossy = sum(1 for r in records if r["table_lossy"])
                math_lossy = sum(1 for r in records if r["math_lossy"])
                overflow = sum(1 for r in records if r["split_overflow"])
                print(
                    f"[{year}/{subject}] {len(records)}문항 저장"
                    f" (표의심 {lossy}, 수식유실 {math_lossy}, 분할경고 {overflow},"
                    f" 제외 {len(issues)}: {issues[:3]})"
                )
                total_ok += len(records)
    print(f"[done] 총 {total_ok}문항")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
