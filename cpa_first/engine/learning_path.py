"""약점 개념 → 선수개념 역추적 학습 경로 엔진.

weak_concepts(aggregate.py가 산출한 concept 라벨 문자열)를 용어 그래프의
term에 매칭한 뒤, prerequisite_terms를 BFS로 역추적해
"무엇부터 공부해야 하는지" 순서를 산출한다.

설계 원칙:
  - 결정론: 동일 입력 → 동일 출력 (Date/random 금지, 모든 정렬에 고정 tie-break)
  - 근거 추적: 모든 경로 항목에 한국어 why + evidence_refs 호환 참조 첨부
  - 순환 방어: visited 집합으로 prerequisite 순환 그래프에서도 종료 보장

입력 데이터:
  terms_full — data/seeds/terms/*.term.json 원본 dict (term_id 키)
  edges      — cpa_first.rag.TermIndex.edges (Edge dataclass) 또는 동일 키의 dict
"""

from __future__ import annotations

from collections import deque
from typing import Any

# 자원 종류별 출력 키와 id 필드명. to_kind="term"(confusable/prerequisite 엣지)은 자원이 아니므로 제외.
_RESOURCE_KINDS: dict[str, tuple[str, str]] = {
    "rag_chunk": ("chunks", "chunk_id"),
    "problem": ("problems", "problem_id"),
    "tutorial": ("tutorials", "tutorial_id"),
}

# to_kind별 상위 weight 자원 최대 개수
MAX_RESOURCES_PER_KIND = 3

# 표면형 최소 길이 — TermIndex._surface_forms와 동일 규칙(1글자 표면형은 오매칭 위험)
_MIN_FORM_LEN = 2


def _edge_value(edge: Any, name: str) -> Any:
    """Edge dataclass(TermIndex.edges)와 plain dict 양쪽을 지원하는 접근자."""
    if isinstance(edge, dict):
        return edge[name]
    return getattr(edge, name)


def _surface_forms(term: dict) -> list[str]:
    """매칭 대상 표면형: name_ko + aliases. 너무 짧은 표면형은 제외."""
    forms = [term.get("name_ko") or "", *(term.get("aliases") or [])]
    return [f for f in forms if len(f) >= _MIN_FORM_LEN]


def _label_variants(label: str) -> list[str]:
    """concept 라벨의 매칭 시도 변형: 전체 문자열 → 콜론 뒤 부분 순서."""
    normalized = label.replace("：", ":").strip()
    variants = [normalized] if normalized else []
    if ":" in normalized:
        tail = normalized.split(":", 1)[1].strip()
        if tail and tail not in variants:
            variants.append(tail)
    return variants


def _match_concept(label: str, terms_full: dict[str, dict]) -> str | None:
    """weak_concept 라벨을 term_id로 매칭. 실패 시 None.

    변형(전체 → 콜론 뒤) 순서대로 시도하고, 변형 하나에서 후보가 나오면 즉시 확정.
    후보 우선순위(결정론):
      0) 완전 일치
      1) 표면형이 라벨에 포함 (긴 표면형 우선 — 더 구체적인 매칭)
      2) 라벨이 표면형에 포함 (짧은 표면형 우선 — 라벨과 길이가 가까운 매칭)
    동순위는 term_id 오름차순.
    """
    for variant in _label_variants(label):
        candidates: list[tuple[int, int, str]] = []
        for term_id in sorted(terms_full):
            for form in _surface_forms(terms_full[term_id]):
                if variant == form:
                    rank, length_key = 0, -len(form)
                elif form in variant:
                    rank, length_key = 1, -len(form)
                elif variant in form:
                    rank, length_key = 2, len(form)
                else:
                    continue
                candidates.append((rank, length_key, term_id))
        if candidates:
            candidates.sort()
            return candidates[0][2]
    return None


def _trace_prerequisites(
    roots: list[tuple[str, str]],
    terms_full: dict[str, dict],
    max_depth: int,
) -> dict[str, dict]:
    """약점 term들에서 prerequisite_terms를 BFS 역추적.

    반환: term_id → {"depth": int, "why": str}.
    BFS이므로 depth는 최소 깊이로 확정되고, visited(=결과 dict)로 순환을 방어한다.
    """
    nodes: dict[str, dict] = {}
    queue: deque[tuple[str, str, int]] = deque()

    for term_id, label in roots:
        if term_id in nodes:
            continue
        nodes[term_id] = {
            "depth": 0,
            "why": f"약점 개념 '{label}'에 직접 매칭된 용어 — 이 경로의 최종 목표다.",
        }
        queue.append((term_id, label, 0))

    while queue:
        term_id, root_label, depth = queue.popleft()
        if depth >= max_depth:
            continue
        current = terms_full[term_id]
        for prereq_id in current.get("prerequisite_terms") or []:
            if prereq_id in nodes:
                # 이미 방문(다른 경로 또는 순환) — 최소 depth 유지
                continue
            prereq = terms_full.get(prereq_id)
            if prereq is None:
                # 시드에 없는 term_id는 이름/과목을 알 수 없으므로 경로에서 제외
                continue
            nodes[prereq_id] = {
                "depth": depth + 1,
                "why": (
                    f"'{current.get('name_ko', term_id)}'의 선수개념 — "
                    f"약점 '{root_label}'에서 {depth + 1}단계 역추적했다."
                ),
            }
            queue.append((prereq_id, root_label, depth + 1))
    return nodes


def _resources_index(edges: list) -> dict[str, dict[str, list[dict]]]:
    """from_term별 자원 엣지를 to_kind 그룹으로 인덱싱하고 상위 weight 순 절단."""
    grouped: dict[str, dict[str, list[dict]]] = {}
    for edge in edges:
        kind = _edge_value(edge, "to_kind")
        if kind not in _RESOURCE_KINDS:
            continue
        key, id_field = _RESOURCE_KINDS[kind]
        from_term = _edge_value(edge, "from_term")
        bucket = grouped.setdefault(from_term, {k: [] for k, _ in _RESOURCE_KINDS.values()})
        bucket[key].append(
            {id_field: _edge_value(edge, "to_id"), "weight": float(_edge_value(edge, "weight"))}
        )
    for bucket in grouped.values():
        for key, id_field in _RESOURCE_KINDS.values():
            bucket[key].sort(key=lambda r, f=id_field: (-r["weight"], r[f]))
            del bucket[key][MAX_RESOURCES_PER_KIND:]
    return grouped


def _empty_resources() -> dict[str, list]:
    return {key: [] for key, _ in _RESOURCE_KINDS.values()}


def _confusables(term: dict, terms_full: dict[str, dict]) -> list[dict]:
    """confusable_with 항목 중 시드에 존재하는 term만 name_ko를 붙여 반환."""
    out: list[dict] = []
    for item in term.get("confusable_with") or []:
        other = terms_full.get(item.get("term_id", ""))
        if other is None:
            continue
        out.append(
            {
                "term_id": item["term_id"],
                "name_ko": other.get("name_ko", item["term_id"]),
                "reason": item.get("reason", ""),
            }
        )
    return out


def build_learning_path(
    weak_concepts: list[str],
    terms_full: dict[str, dict],
    edges: list,
    *,
    max_nodes: int = 12,
    max_depth: int = 3,
) -> dict:
    """약점 개념 목록에서 선수개념을 역추적해 학습 순서를 산출한다.

    학습 순서 = 깊은 선수개념 먼저(depth 내림차순), 같은 depth는 term_id 오름차순.
    max_nodes 초과 시 약점 자체(depth 0)를 우선 보존하고, 약점에 가까운
    (depth가 작은) 선수개념부터 채운 뒤 나머지를 잘라낸다.
    """
    roots: list[tuple[str, str]] = []
    matched_term_ids: set[str] = set()
    unmatched: list[str] = []
    for label in weak_concepts:
        term_id = _match_concept(label, terms_full)
        if term_id is None:
            if label not in unmatched:
                unmatched.append(label)
        elif term_id not in matched_term_ids:
            matched_term_ids.add(term_id)
            roots.append((term_id, label))

    nodes = _trace_prerequisites(roots, terms_full, max_depth)

    # 절단: depth 오름차순(약점 자체 우선 보존) + term_id 오름차순
    selection_order = sorted(nodes, key=lambda t: (nodes[t]["depth"], t))
    selected = selection_order[: max(0, max_nodes)]

    # 출력 정렬: depth 내림차순(깊은 선수개념 먼저 학습) + term_id 오름차순
    ordered = sorted(selected, key=lambda t: (-nodes[t]["depth"], t))

    resources_by_term = _resources_index(edges)

    path: list[dict] = []
    evidence_refs: list[dict] = []
    for term_id in ordered:
        term = terms_full[term_id]
        why = nodes[term_id]["why"]
        path.append(
            {
                "term_id": term_id,
                "name_ko": term.get("name_ko", term_id),
                "subject": term.get("subject", ""),
                "depth": nodes[term_id]["depth"],
                "why": why,
                "resources": resources_by_term.get(term_id, _empty_resources()),
                "confusable_with": _confusables(term, terms_full),
            }
        )
        evidence_refs.append({"ref_type": "term", "ref_id": term_id, "note": why})

    return {
        "path": path,
        "unmatched_concepts": unmatched,
        "evidence_refs": evidence_refs,
    }
