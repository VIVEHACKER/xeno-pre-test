"""키워드 + 메타데이터 기반 검색.

점수: tag/keyword 가중치 매칭 + 본문 토큰 overlap.
정렬: 점수 desc, chunk_id asc (결정론).
필터: subject, unit (옵션). 같은 과목 우선이지만 general은 항상 후보.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# 토큰화 — 한국어/영문 혼합. 2글자 이상 한글/영숫자 토큰 추출.
_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


@dataclass
class RagChunk:
    chunk_id: str
    subject: str
    unit: str | None
    topic_tags: list[str]
    text: str
    keywords: list[str] = field(default_factory=list)
    title: str = ""
    reference: str | None = None
    applicable_year: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RagChunk":
        return cls(
            chunk_id=data["chunk_id"],
            subject=data["subject"],
            unit=data.get("unit"),
            topic_tags=list(data.get("topic_tags") or []),
            text=data["text"],
            keywords=list(data.get("keywords") or []),
            title=data.get("source", {}).get("title", ""),
            reference=data.get("source", {}).get("reference"),
            applicable_year=data.get("applicable_year"),
        )


@dataclass
class RetrievalHit:
    chunk: RagChunk
    score: float


def load_chunks(directory: Path) -> list[RagChunk]:
    out: list[RagChunk] = []
    for path in sorted(Path(directory).glob("*.rag_chunk.json")):
        with path.open("r", encoding="utf-8") as f:
            out.append(RagChunk.from_dict(json.load(f)))
    return out


def retrieve(
    query: str,
    chunks: list[RagChunk],
    *,
    subject: str | None = None,
    unit: str | None = None,
    top_k: int = 3,
    min_score: float = 0.5,
) -> list[RetrievalHit]:
    """query 텍스트로 chunks를 검색. 점수 desc + chunk_id asc 정렬.

    필터:
      - subject가 주어지면 동일 subject 또는 general만 후보.
      - unit이 주어지면 부분 매칭 시 가중치 가산.
    """
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []

    candidates: list[RetrievalHit] = []
    for chunk in chunks:
        if subject and chunk.subject not in (subject, "general"):
            continue
        score = _score_chunk(chunk, query_tokens, query, unit)
        if score >= min_score:
            candidates.append(RetrievalHit(chunk=chunk, score=score))

    candidates.sort(key=lambda h: (-h.score, h.chunk.chunk_id))
    return candidates[:top_k]


def _score_chunk(
    chunk: RagChunk,
    query_tokens: set[str],
    raw_query: str,
    unit: str | None,
) -> float:
    score = 0.0

    # 1) keyword 매칭 (가장 강한 신호)
    for kw in chunk.keywords:
        if any(part in raw_query for part in (kw, kw.lower())):
            score += 2.0
        elif _tokenize(kw) and set(_tokenize(kw)) & query_tokens:
            score += 1.0

    # 2) topic_tag 매칭
    for tag in chunk.topic_tags:
        tag_tokens = set(_tokenize(tag))
        if tag_tokens & query_tokens:
            score += 0.8

    # 3) 본문 token overlap (희석된 신호)
    body_tokens = set(_tokenize(chunk.text))
    overlap = body_tokens & query_tokens
    if overlap:
        # query 길이로 정규화. 너무 길면 분모 커져 점수 안정.
        score += min(len(overlap) / max(len(query_tokens), 1), 1.0) * 1.5

    # 4) unit 매칭 가산
    if unit and chunk.unit:
        if unit == chunk.unit:
            score += 1.0
        elif unit in chunk.unit or chunk.unit in unit:
            score += 0.5

    # 5) subject 일치는 필터로 처리 + general은 가산 없음
    # (subject가 다른 chunk는 후보에서 빠짐)

    return round(score, 4)


def format_context(hits: list[RetrievalHit]) -> str:
    """검색된 chunk를 LLM에 주입할 텍스트로 직렬화."""
    if not hits:
        return ""
    parts: list[str] = ["[참고 자료]"]
    for hit in hits:
        ref = f" ({hit.chunk.reference})" if hit.chunk.reference else ""
        parts.append(f"- {hit.chunk.title}{ref}")
        parts.append(f"  {hit.chunk.text}")
    return "\n".join(parts)
