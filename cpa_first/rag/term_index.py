"""용어 지식 그래프 인덱스.

쿼리 토큰 확장 + chunk와 term 간 엣지 역인덱스를 제공한다.
search.retrieve()가 옵션으로 받아 점수에 반영한다.

데이터 소스:
  data/seeds/terms/*.term.json          — 노드
  data/seeds/term_graph/edges.jsonl     — 엣지 (한 줄 = 하나)

설계: docs/specs/2026-05-12-term-knowledge-graph-design.md §7
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_ASCII_TOKEN_RE = re.compile(r"^[A-Za-z0-9]+$")


def _contains(haystack: str, needle: str) -> bool:
    """ASCII 단축어는 단어 경계로, 한글 포함 어휘는 substring으로 매칭.

    builder의 동명 함수와 의도적으로 동일한 규칙. 매칭 일관성을 위해 양쪽이 같이 변경되어야 한다.
    """
    if not needle:
        return False
    if _ASCII_TOKEN_RE.fullmatch(needle):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(needle) + r"(?![A-Za-z0-9])"
        return bool(re.search(pattern, haystack))
    return needle in haystack


@dataclass(frozen=True)
class Term:
    term_id: str
    name_ko: str
    aliases: tuple[str, ...] = ()
    confusable_with: tuple[str, ...] = ()  # 다른 term_id 목록

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Term":
        return cls(
            term_id=data["term_id"],
            name_ko=data["name_ko"],
            aliases=tuple(data.get("aliases") or ()),
            confusable_with=tuple(
                c["term_id"] for c in (data.get("confusable_with") or [])
            ),
        )


@dataclass(frozen=True)
class Edge:
    from_term: str
    to_kind: str
    to_id: str
    relation: str
    weight: float

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Edge":
        return cls(
            from_term=data["from_term"],
            to_kind=data["to_kind"],
            to_id=data["to_id"],
            relation=data["relation"],
            weight=float(data["weight"]),
        )


def load_terms(terms_dir: Path) -> list[Term]:
    out: list[Term] = []
    for path in sorted(Path(terms_dir).glob("*.term.json")):
        with path.open("r", encoding="utf-8") as f:
            out.append(Term.from_dict(json.load(f)))
    return out


def load_edges(edges_path: Path) -> list[Edge]:
    out: list[Edge] = []
    path = Path(edges_path)
    if not path.exists():
        return out
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(Edge.from_dict(json.loads(line)))
    return out


@dataclass
class TermIndex:
    """용어 지식 그래프 조회 인덱스.

    matched_terms(query)         → 쿼리에 등장한 term_id 집합
    expand_query(query)          → matched terms의 표면형 + 시드 내 confusable 표면형 집합
    chunk_defined_by(chunk_id)   → 해당 chunk를 정의하는 term_id 집합 (defined_in 엣지)
    related_chunks(term_id)      → 해당 term이 defined_in/explained_in으로 연결된 chunk_id 목록
    """

    terms: list[Term]
    edges: list[Edge] = field(default_factory=list)

    _by_id: dict[str, Term] = field(init=False, repr=False)
    _chunk_to_terms: dict[str, set[str]] = field(init=False, repr=False)
    _term_to_chunks: dict[str, list[str]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_id = {t.term_id: t for t in self.terms}
        self._chunk_to_terms = defaultdict(set)
        self._term_to_chunks = defaultdict(list)
        for edge in self.edges:
            if edge.to_kind == "rag_chunk" and edge.relation == "defined_in":
                self._chunk_to_terms[edge.to_id].add(edge.from_term)
                self._term_to_chunks[edge.from_term].append(edge.to_id)

    @classmethod
    def from_paths(cls, terms_dir: Path, edges_path: Path) -> "TermIndex":
        return cls(terms=load_terms(terms_dir), edges=load_edges(edges_path))

    def matched_terms(self, query: str) -> set[str]:
        """쿼리에 표면형이 등장한 term_id들."""
        matched: set[str] = set()
        for term in self.terms:
            for form in self._surface_forms(term):
                if _contains(query, form):
                    matched.add(term.term_id)
                    break
        return matched

    def expand_query(self, query: str) -> set[str]:
        """쿼리에 등장한 term들의 표면형 + 시드에 존재하는 confusable 표면형."""
        expanded: set[str] = set()
        for tid in self.matched_terms(query):
            term = self._by_id[tid]
            expanded.update(self._surface_forms(term))
            for confusable_id in term.confusable_with:
                other = self._by_id.get(confusable_id)
                if other is not None:
                    expanded.update(self._surface_forms(other))
        return expanded

    def chunk_defined_by(self, chunk_id: str) -> set[str]:
        return self._chunk_to_terms.get(chunk_id, set())

    def related_chunks(self, term_id: str) -> list[str]:
        return list(self._term_to_chunks.get(term_id, []))

    @staticmethod
    def _surface_forms(term: Term) -> list[str]:
        forms = [term.name_ko, *term.aliases]
        return [f for f in forms if len(f) >= 2]
