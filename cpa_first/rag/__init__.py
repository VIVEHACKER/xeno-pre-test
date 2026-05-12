"""RAG v1 — 자체 요약본 키워드 기반 검색.

외부 의존(BM25, embeddings) 없이 token overlap + 가중치로 시작.
v2에서 embedding 검색으로 갈 자리이지만 현재 시드 수에는 과한 도구.
"""

from cpa_first.rag.search import (
    RagChunk,
    RetrievalHit,
    format_context,
    load_chunks,
    retrieve,
)
from cpa_first.rag.term_index import Edge, Term, TermIndex, load_edges, load_terms

__all__ = [
    "RagChunk",
    "RetrievalHit",
    "format_context",
    "load_chunks",
    "retrieve",
    "Term",
    "Edge",
    "TermIndex",
    "load_terms",
    "load_edges",
]
