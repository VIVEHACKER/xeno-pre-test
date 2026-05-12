"""평가셋 JSON 파일 저장.

다음 question_id를 자동 발급하고, 기존 파일을 덮어쓰지 않는다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_ID_PATTERN = re.compile(r"^cpa1-eval-(?P<subject>[a-z_]+)-(?P<num>\d+)$")


def next_question_id(subject: str, target_dir: Path) -> str:
    """target_dir에서 cpa1-eval-{subject}-NNN 형식 최대값 + 1을 반환."""
    target_dir = Path(target_dir)
    if not target_dir.exists():
        return f"cpa1-eval-{subject}-001"

    max_num = 0
    for path in target_dir.glob(f"cpa1-eval-{subject}-*.evaluation_question.json"):
        stem = path.name.replace(".evaluation_question.json", "")
        m = _ID_PATTERN.match(stem)
        if not m:
            continue
        if m.group("subject") != subject:
            continue
        try:
            n = int(m.group("num"))
            max_num = max(max_num, n)
        except ValueError:
            continue

    return f"cpa1-eval-{subject}-{max_num + 1:03d}"


def write_question(question: dict[str, Any], target_dir: Path) -> Path:
    """다음 ID를 발급해 JSON 파일로 저장. 파일이 우연히 존재하면 다음 번호로.

    question["subject"] 필수 — 누락 시 ValueError.
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    subject = question.get("subject")
    if not subject:
        raise ValueError("question['subject'] is required")

    while True:
        qid = next_question_id(subject, target_dir)
        path = target_dir / f"{qid}.evaluation_question.json"
        if not path.exists():
            break
        # 경합 방지: 같은 번호 파일이 이미 있으면 다음 번호로 (드물지만 안전)
        (target_dir / f"{qid}.evaluation_question.json").touch()
        # 다음 호출 시 max_num이 증가하도록 빈 파일이 카운트되므로 OK

    question = dict(question)
    question["question_id"] = qid

    with path.open("w", encoding="utf-8") as f:
        json.dump(question, f, ensure_ascii=False, indent=2)

    return path
