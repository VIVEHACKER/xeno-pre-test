"""공인회계사 1차 실기출 수집 — 금융감독원 공식 게시판에서만 다운로드한다.

권리 게이트 (data/seeds/past_exam_assets.csv 정책 준수):
- 출처: cpa.fss.or.kr 공식 '기출문제' 게시판(B0000368)만. 학원/블로그 미러 금지.
- 용도: 평가(eval) 전용. RAG/학습 투입은 training_policy=train_after_rights_review에 따라
  권리 검토 후에만.
- 저장: data/real_exams/ (gitignore — 원문 재배포 회피, provenance manifest만 기록).

사용:
    .venv/bin/python scripts/collect_real_exams.py            # 등록된 3개년 전부
    .venv/bin/python scripts/collect_real_exams.py --years 2026
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

BASE = "https://cpa.fss.or.kr"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

# 연도별 게시글. 확정답안 게시글이 문제지를 함께 갖기도(2026), 가답안 게시글에만
# 문제지가 있기도(2024 PDF, 2025 ZIP) 하다 — 둘 다 등록해 합집합을 받는다.
POSTS = {
    2026: {"round": 61, "ntt_ids": [215021]},
    2025: {"round": 60, "ntt_ids": [191846, 191366]},
    2024: {"round": 59, "ntt_ids": [134641, 134086]},
}

_HREF_RE = re.compile(
    r'href="(/cpa/cmmn/file/fileDown\.do[^"]*)"[^>]*>\s*<img[^>]*alt="([^"]+?)\s*다운로드"'
)

_ALLOWED_EXT = (".pdf", ".zip")


def list_attachments(client: httpx.Client, ntt_id: int) -> list[tuple[str, str]]:
    """게시글의 (다운로드 URL, 파일명) 목록. PDF/ZIP만."""
    url = f"{BASE}/cpa/bbs/B0000368/view.do?nttId={ntt_id}&menuNo=1200078&pageIndex=1"
    resp = client.get(url)
    resp.raise_for_status()
    out: list[tuple[str, str]] = []
    for href, filename in _HREF_RE.findall(resp.text):
        if filename.lower().endswith(_ALLOWED_EXT):
            out.append((BASE + href.replace("&amp;", "&"), filename))
    return out


def extract_zip(zip_path: Path) -> list[str]:
    """ZIP 안의 PDF를 같은 디렉터리에 푼다. 풀린 파일명 목록 반환."""
    import zipfile

    extracted: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                continue
            # 한글 파일명: ZIP 표준 cp437 저장분은 cp949로 복원 (UTF-8 플래그면 그대로)
            name = info.filename
            if not info.flag_bits & 0x800:
                try:
                    name = info.filename.encode("cp437").decode("cp949")
                except (UnicodeEncodeError, UnicodeDecodeError):
                    pass
            dest = zip_path.parent / Path(name).name
            if not dest.exists():
                dest.write_bytes(zf.read(info))
            extracted.append(dest.name)
    return extracted


def download(client: httpx.Client, url: str, dest: Path) -> str:
    """파일 다운로드 후 sha256 반환. 이미 있으면 스킵(해시만 재계산)."""
    if not dest.exists():
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
        time.sleep(1.0)  # 공식 서버 부담 최소화
    return hashlib.sha256(dest.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="", help="쉼표구분 연도 (기본: 전부)")
    ap.add_argument("--out-dir", type=Path, default=Path("data/real_exams/cpa1"))
    args = ap.parse_args()

    years = [int(y) for y in args.years.split(",") if y.strip()] if args.years else sorted(POSTS)
    manifest_path = args.out_dir / "manifest.json"
    manifest: dict = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )

    with httpx.Client(headers={"User-Agent": UA}, timeout=60, follow_redirects=True) as client:
        for year in years:
            post = POSTS[year]
            year_dir = args.out_dir / str(year)
            entries = []
            for ntt_id in post["ntt_ids"]:
                attachments = list_attachments(client, ntt_id)
                if not attachments:
                    print(f"[{year}] nttId={ntt_id} 첨부 PDF/ZIP 없음", file=sys.stderr)
                    continue
                for url, filename in attachments:
                    dest = year_dir / filename
                    sha = download(client, url, dest)
                    entry = {
                        "filename": filename,
                        "post_nttId": ntt_id,
                        "source_url": url,
                        "sha256": sha,
                        "bytes": dest.stat().st_size,
                        "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    }
                    if filename.lower().endswith(".zip"):
                        entry["extracted"] = extract_zip(dest)
                    entries.append(entry)
                    print(f"[{year}] {filename} ({dest.stat().st_size:,}B)")
            if not entries:
                print(f"[{year}] 수집 실패 — 게시글 구조 변경 가능성", file=sys.stderr)
                continue
            manifest[str(year)] = {
                "exam": "CPA_1",
                "round": post["round"],
                "post_ntt_ids": post["ntt_ids"],
                "source_owner": "금융감독원",
                "rights_policy": "official_download_check_required",
                "usage": "evaluation_only",
                "training_policy": "train_after_rights_review",
                "files": entries,
            }

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"[manifest] {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
