"""용어 지식 그래프 엣지 빌더.

입력:
  data/seeds/terms/*.term.json              — 노드 (사람/LLM 작성)
  data/seeds/rag/*.rag_chunk.json           — RAG 청크
  data/seeds/problems/*.problem_intelligence.json — 문제 지능
  data/seeds/subject_tutorials.json         — 튜토리얼

출력:
  data/seeds/term_graph/edges.jsonl         — 엣지 (한 줄 = 하나의 엣지)

결정론: 입력 파일 정렬, 엣지 정렬키 (from_term, to_kind, to_id, relation, weight desc).
        동일 입력은 항상 동일 출력을 만든다.

매칭 규칙 (설계 문서 §6):
  defined_in       — term.name_ko/aliases가 chunk.keywords에 있음 → 2.0
                     본문에만 등장 → 1.0
  tested_in        — required_concepts[].concept 정확 일치 → 2.0
                     concept_tags 부분 매칭 → 1.0
  explained_in     — 튜토리얼 본문에 등장 → 1.0
  confusable_with  — term.confusable_with[]를 양방향 엣지로 → 1.0
  prerequisite_of  — term.prerequisite_terms[]를 역방향 엣지로 → 1.0
                     ("P가 X의 선수" → P --prerequisite_of--> X)

사용:
  python scripts/build_term_graph.py             # 빌드 후 파일 갱신
  python scripts/build_term_graph.py --dry-run   # 표준출력에 요약만
  python scripts/build_term_graph.py --root DIR  # 다른 루트 (테스트용)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ASCII_TOKEN_RE = re.compile(r"^[A-Za-z0-9]+$")


@dataclass(frozen=True)
class Edge:
    from_term: str
    to_kind: str          # "rag_chunk" | "problem" | "tutorial" | "term"
    to_id: str
    relation: str         # "defined_in" | "tested_in" | "explained_in" | "confusable_with" | "prerequisite_of"
    weight: float
    evidence: str | None  # 어디서 매치됐는지 1줄

    def sort_key(self) -> tuple:
        return (self.from_term, self.to_kind, self.to_id, self.relation, -self.weight)

    def to_dict(self) -> dict[str, Any]:
        return {
            "from_term": self.from_term,
            "to_kind": self.to_kind,
            "to_id": self.to_id,
            "relation": self.relation,
            "weight": self.weight,
            "evidence": self.evidence,
        }


def _contains(haystack: str, needle: str) -> bool:
    """ASCII-only needle은 단어 경계로, 한글 포함 needle은 단순 substring으로."""
    if not needle:
        return False
    if ASCII_TOKEN_RE.fullmatch(needle):
        pattern = r"(?<![A-Za-z0-9])" + re.escape(needle) + r"(?![A-Za-z0-9])"
        return bool(re.search(pattern, haystack))
    return needle in haystack


def _surface_forms(term: dict) -> list[str]:
    """매칭에 사용할 표면 형태 목록 (name_ko + aliases). 빈 문자열 제거."""
    forms: list[str] = [term["name_ko"]]
    forms.extend(a for a in term.get("aliases", []) if a)
    # 길이 1 짜리 별칭은 너무 광범위해 제외 (예: "Δ")
    return [f for f in forms if len(f) >= 2]


def _serialize(obj: Any) -> str:
    """객체를 한 덩어리 텍스트로 직렬화 (튜토리얼 본문 등 nested 매칭용)."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (int, float, bool)) or obj is None:
        return str(obj)
    if isinstance(obj, dict):
        return " ".join(_serialize(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return " ".join(_serialize(v) for v in obj)
    return str(obj)


# ── 로더 ─────────────────────────────────────────────────────────────────


def load_terms(terms_dir: Path) -> list[dict]:
    out: list[dict] = []
    for path in sorted(terms_dir.glob("*.term.json")):
        with path.open("r", encoding="utf-8") as f:
            out.append(json.load(f))
    return out


def load_chunks(rag_dir: Path) -> list[dict]:
    out: list[dict] = []
    for path in sorted(rag_dir.glob("*.rag_chunk.json")):
        with path.open("r", encoding="utf-8") as f:
            out.append(json.load(f))
    return out


def load_problems(problems_dir: Path) -> list[dict]:
    out: list[dict] = []
    for path in sorted(problems_dir.glob("*.problem_intelligence.json")):
        with path.open("r", encoding="utf-8") as f:
            out.append(json.load(f))
    return out


def load_tutorials(tutorials_path: Path) -> list[dict]:
    if not tutorials_path.exists():
        return []
    with tutorials_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("tutorials", []))


# ── 매칭 ─────────────────────────────────────────────────────────────────


def edges_to_rag(terms: list[dict], chunks: list[dict]) -> list[Edge]:
    """defined_in 엣지. keywords 일치 우선, 본문 매칭은 fallback."""
    edges: list[Edge] = []
    for term in terms:
        forms = _surface_forms(term)
        for chunk in chunks:
            keywords = [k for k in chunk.get("keywords", []) if k]
            text = chunk.get("text", "")

            kw_hit = next((f for f in forms if f in keywords), None)
            if kw_hit:
                edges.append(Edge(
                    from_term=term["term_id"],
                    to_kind="rag_chunk",
                    to_id=chunk["chunk_id"],
                    relation="defined_in",
                    weight=2.0,
                    evidence=f"keyword match: {kw_hit}",
                ))
                continue

            body_hit = next((f for f in forms if _contains(text, f)), None)
            if body_hit:
                edges.append(Edge(
                    from_term=term["term_id"],
                    to_kind="rag_chunk",
                    to_id=chunk["chunk_id"],
                    relation="defined_in",
                    weight=1.0,
                    evidence=f"body match: {body_hit}",
                ))
    return edges


def edges_to_problems(terms: list[dict], problems: list[dict]) -> list[Edge]:
    """tested_in 엣지. required_concepts[].concept 정확 일치 우선, concept_tags 부분 매칭은 fallback."""
    edges: list[Edge] = []
    for term in terms:
        forms = _surface_forms(term)
        for problem in problems:
            concepts = [c["concept"] for c in problem.get("required_concepts", [])]
            tags = problem.get("concept_tags", [])

            exact = next((f for f in forms if f in concepts), None)
            if exact:
                edges.append(Edge(
                    from_term=term["term_id"],
                    to_kind="problem",
                    to_id=problem["problem_id"],
                    relation="tested_in",
                    weight=2.0,
                    evidence=f"required_concepts: {exact}",
                ))
                continue

            partial = next(
                (f for f in forms if any(_contains(tag, f) for tag in tags)),
                None,
            )
            if partial:
                edges.append(Edge(
                    from_term=term["term_id"],
                    to_kind="problem",
                    to_id=problem["problem_id"],
                    relation="tested_in",
                    weight=1.0,
                    evidence=f"concept_tags partial: {partial}",
                ))
    return edges


def edges_to_tutorials(terms: list[dict], tutorials: list[dict]) -> list[Edge]:
    """explained_in 엣지. 튜토리얼 전체 본문 substring 매칭."""
    edges: list[Edge] = []
    tutorial_texts = [(t["tutorial_id"], _serialize(t)) for t in tutorials]
    for term in terms:
        forms = _surface_forms(term)
        for tut_id, text in tutorial_texts:
            hit = next((f for f in forms if _contains(text, f)), None)
            if hit:
                edges.append(Edge(
                    from_term=term["term_id"],
                    to_kind="tutorial",
                    to_id=tut_id,
                    relation="explained_in",
                    weight=1.0,
                    evidence=f"tutorial body: {hit}",
                ))
    return edges


def edges_confusable(terms: list[dict]) -> list[Edge]:
    """confusable_with 엣지. 양방향으로 생성."""
    edges: list[Edge] = []
    for term in terms:
        for pair in term.get("confusable_with", []):
            edges.append(Edge(
                from_term=term["term_id"],
                to_kind="term",
                to_id=pair["term_id"],
                relation="confusable_with",
                weight=1.0,
                evidence=pair.get("reason"),
            ))
            edges.append(Edge(
                from_term=pair["term_id"],
                to_kind="term",
                to_id=term["term_id"],
                relation="confusable_with",
                weight=1.0,
                evidence=pair.get("reason"),
            ))
    return edges


def edges_prerequisite(terms: list[dict]) -> list[Edge]:
    """prerequisite_of 엣지. X의 prereq가 P면, P -> X 방향으로 'P는 X의 선수다'."""
    edges: list[Edge] = []
    for term in terms:
        for prereq_id in term.get("prerequisite_terms", []):
            edges.append(Edge(
                from_term=prereq_id,
                to_kind="term",
                to_id=term["term_id"],
                relation="prerequisite_of",
                weight=1.0,
                evidence=f"{prereq_id} required before {term['term_id']}",
            ))
    return edges


# ── 통합 ─────────────────────────────────────────────────────────────────


def build_edges(
    terms: list[dict],
    chunks: list[dict],
    problems: list[dict],
    tutorials: list[dict],
) -> list[Edge]:
    """모든 매처를 실행하고 중복 제거 + 정렬."""
    all_edges: list[Edge] = []
    all_edges.extend(edges_to_rag(terms, chunks))
    all_edges.extend(edges_to_problems(terms, problems))
    all_edges.extend(edges_to_tutorials(terms, tutorials))
    all_edges.extend(edges_confusable(terms))
    all_edges.extend(edges_prerequisite(terms))

    # 동일 (from, to_kind, to_id, relation)은 weight 큰 것만 남긴다.
    seen: dict[tuple[str, str, str, str], Edge] = {}
    for edge in all_edges:
        key = (edge.from_term, edge.to_kind, edge.to_id, edge.relation)
        existing = seen.get(key)
        if existing is None or edge.weight > existing.weight:
            seen[key] = edge

    deduped = list(seen.values())
    deduped.sort(key=Edge.sort_key)
    return deduped


def write_edges(edges: Iterable[Edge], out_path: Path) -> int:
    """edges.jsonl 작성. JSON Lines, UTF-8, LF 종료."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        for edge in edges:
            f.write(json.dumps(edge.to_dict(), ensure_ascii=False, sort_keys=True))
            f.write("\n")
            count += 1
    return count


def summarize(edges: list[Edge]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for edge in edges:
        summary[edge.relation] = summary.get(edge.relation, 0) + 1
    summary["__total__"] = len(edges)
    return summary


# ── CLI ──────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="용어 지식 그래프 엣지 빌더")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="프로젝트 루트 (기본: 스크립트 부모의 부모)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="edges.jsonl을 쓰지 않고 요약만 출력",
    )
    args = parser.parse_args(argv)

    root: Path = args.root
    terms = load_terms(root / "data" / "seeds" / "terms")
    chunks = load_chunks(root / "data" / "seeds" / "rag")
    problems = load_problems(root / "data" / "seeds" / "problems")
    tutorials = load_tutorials(root / "data" / "seeds" / "subject_tutorials.json")

    edges = build_edges(terms, chunks, problems, tutorials)
    summary = summarize(edges)

    print(f"terms={len(terms)} chunks={len(chunks)} problems={len(problems)} tutorials={len(tutorials)}")
    print("edges by relation:")
    for relation in sorted(k for k in summary if k != "__total__"):
        print(f"  {relation}: {summary[relation]}")
    print(f"  TOTAL: {summary['__total__']}")

    if args.dry_run:
        print("(dry-run: edges.jsonl was not written)")
        return 0

    out_path = root / "data" / "seeds" / "term_graph" / "edges.jsonl"
    written = write_edges(edges, out_path)
    print(f"wrote {written} edges to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
