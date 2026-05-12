# Term Knowledge Graph — 설계 스케치

> CPA 1차 학습용 "어려운/생소한/중요한 용어"를 노드로, 기존 RAG 청크·문제·튜토리얼을 엣지로 잇는 검색 가능한 지식 그래프. 사용자 선택: "RAG 청크 + 용어 인덱스 통합".

생성일: 2026-05-12
범위: data 레이어 신규 스키마 + seed + 빌더 스크립트 + 검색 확장 (Tier 2)
근거: harness.md Design Sketch 프로토콜 (mp-tdd, brainstorming 패턴)

---

## 1. Problem Restated

기존 자료에는 용어가 **세 군데에 흩어져 중복·불일치 상태**다.

| 위치 | 형태 | 문제 |
|------|------|------|
| `rag_chunk.json#keywords` | 단순 문자열 배열 | 정의·동의어·혼동쌍 없음 |
| `problem_intelligence.json#required_concepts[].concept` | 문자열 + role | 정의가 problem 단위로 흩어짐 |
| `subject_tutorials.json` 본문 | "용어가 비슷해 방향 착각 가능" 같은 산문 | 구조화 안 됨, 검색 불가 |

학습자가 모르는 단어를 만났을 때 → 정의 + 공식 + 헷갈리는 짝 + 관련 문제까지 한 번에 못 본다.

**목표**: 용어 단일 source of truth + RAG/problem/tutorial로의 자동 엣지 + `search.py`에서 함께 검색.

---

## 2. Approaches (A/B/C)

### A. Term-as-Node + 별도 엣지 파일 (추천 ★)
- `data/schemas/term.schema.json` 신규
- `data/seeds/terms/<slug>.term.json` 1용어 1파일 (기존 seed 패턴 일치)
- `data/seeds/term_graph/edges.jsonl` — `{from_term, to_kind, to_id, relation, weight}` append-only
- 빌더 스크립트가 rag/problem/tutorial 스캔 → 엣지 자동 생성
- **장점**: 기존 seed 패턴과 동일, 확장성, 사람이 손으로 편집 가능
- **단점**: 파일 수 증가 (100~200개 예상)

### B. RAG 청크 안에 임베드
- `rag_chunk.schema.json`에 `defined_terms: [{term, definition, synonyms}]` 추가
- **장점**: 변경 최소, 새 디렉토리 없음
- **단점**: 용어가 여러 청크에 중복, 중앙 lookup 불가, 그래프 안 됨 → **요구사항 미충족**

### C. 단일 거대 그래프 JSON
- `data/seeds/term_graph.json` 하나에 nodes + edges 통합
- **장점**: 한눈에 보임
- **단점**: 200+ 노드 시 편집 불가, 머지 충돌, seed 패턴 위배

**결정: A**. 이유 — 기존 `data/seeds/{problems,rag,decision_rules,evaluation}/` 의 1엔티티 1파일 패턴과 일치, 손편집 가능, 빌더가 엣지를 자동 생성하므로 사람 부담은 노드만.

---

## 3. Architecture

```
data/
  schemas/
    term.schema.json              [NEW] 용어 노드 스키마
    term_edge.schema.json         [NEW] 엣지 스키마 (jsonl 라인 1개)
  seeds/
    terms/
      amortized-cost.term.json    [NEW] 1 용어 = 1 파일
      effective-interest-rate.term.json
      ...
    term_graph/
      edges.jsonl                 [NEW] 빌더가 생성 (커밋함, 결정론)

cpa_first/
  rag/
    search.py                     [EXTEND] term_index 통합 검색
    term_index.py                 [NEW] 용어 로드 + 엣지 순회

scripts/
  build_term_graph.py             [NEW] 빌더: rag/problem/tutorial 스캔 → edges.jsonl
```

데이터 흐름:
```
Author writes:  terms/<slug>.term.json  (사람 또는 LLM draft)
Builder runs:   scripts/build_term_graph.py
                ├─ load all terms
                ├─ scan rag_chunks → if term in keywords/text → edge(term → chunk, "defined_in")
                ├─ scan problems  → if term in required_concepts → edge(term → problem, "tested_in")
                ├─ scan tutorials → if term in body → edge(term → tutorial, "explained_in")
                └─ write edges.jsonl (sorted, deterministic)
Search:         search.py.retrieve(query) → term_index.expand(query) → 동의어/혼동쌍까지 쿼리 확장
```

---

## 4. Schema: term.schema.json

```json
{
  "$id": "https://cpa-first.local/schemas/term.schema.json",
  "title": "Term",
  "type": "object",
  "required": ["term_id", "name_ko", "subject", "definition", "review_status"],
  "properties": {
    "term_id": { "type": "string", "pattern": "^[a-z0-9-]+$" },
    "name_ko": { "type": "string" },
    "name_en": { "type": ["string", "null"] },
    "aliases": { "type": "array", "items": { "type": "string" } },
    "subject": { "type": "string", "enum": ["accounting","tax","business","economics","corporate_law","general"] },
    "unit": { "type": ["string", "null"] },
    "definition": { "type": "string", "description": "1-3 문장. 자체 요약 또는 official_paraphrase." },
    "formula": { "type": ["string", "null"], "description": "있을 때만. LaTeX는 금지, 일반 텍스트." },
    "difficulty": { "type": "string", "enum": ["foundational","intermediate","advanced"] },
    "confusable_with": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["term_id", "reason"],
        "properties": {
          "term_id": { "type": "string" },
          "reason": { "type": "string", "description": "왜 헷갈리는지 1문장" }
        }
      }
    },
    "prerequisite_terms": { "type": "array", "items": { "type": "string" } },
    "example": { "type": ["string", "null"] },
    "rights_status": { "type": "string", "enum": ["self_generated","official_paraphrase"] },
    "review_status": { "type": "string", "enum": ["ai_draft","expert_reviewed","approved","rejected"] }
  },
  "additionalProperties": false
}
```

## 5. Schema: term_edge (edges.jsonl 1라인)

```json
{
  "from_term": "amortized-cost",
  "to_kind": "rag_chunk | problem | tutorial | term",
  "to_id": "kifrs-1109-amortized-cost",
  "relation": "defined_in | tested_in | explained_in | confusable_with | prerequisite_of",
  "weight": 1.0,
  "evidence": "matched in keywords"
}
```

엣지는 빌더가 결정론적으로 생성 → 손편집 안 함. `from_term`+`to_id`+`relation`으로 정렬.

---

## 6. Builder: scripts/build_term_graph.py

입력: `data/seeds/terms/*.json`, `data/seeds/rag/*.json`, `data/seeds/problems/*.json`, `prototype/subject_tutorials.json`
출력: `data/seeds/term_graph/edges.jsonl`

매칭 규칙:
1. **defined_in (term → rag_chunk)**: `term.name_ko` 또는 `aliases`가 `chunk.keywords`에 포함 → weight 2.0. 본문에만 등장 → weight 1.0.
2. **tested_in (term → problem)**: `term.name_ko`가 `problem.required_concepts[].concept`와 정확 일치 → weight 2.0. `concept_tags`에 부분 매칭 → 1.0.
3. **explained_in (term → tutorial)**: tutorial 본문에 `term.name_ko` 등장 → 1.0.
4. **confusable_with**: `term.confusable_with[]` 그대로 엣지화 (양방향).
5. **prerequisite_of**: `term.prerequisite_terms[]` → 엣지 역방향.

결정론: 파일 정렬, 엣지 정렬, 일정한 토큰화. 동일 입력 → 동일 edges.jsonl.

---

## 7. Search Integration

`cpa_first/rag/term_index.py` (신규):
```python
def expand_query(query: str, terms: list[Term]) -> set[str]:
    """질문에 등장한 term → aliases + confusable_with 까지 확장된 토큰 집합"""

def related_chunks(term_id: str, edges: list[Edge]) -> list[str]:
    """term → defined_in/explained_in chunk_id 목록"""
```

`search.py.retrieve()` 변경 (최소):
- 쿼리 들어옴 → `expand_query` → 확장된 토큰셋으로 기존 점수 계산
- 점수 +0.5: 매칭된 chunk가 term의 `defined_in` 엣지에도 있을 때 (그래프 일치 보너스)

기존 호출자 인터페이스 불변 (`retrieve(query, chunks, subject=...)`).

---

## 8. Edge Cases & Risks

| 케이스 | 대응 |
|--------|------|
| 같은 단어가 과목별 의미 다름 (예: "원가" 회계 vs 세무) | `term_id`에 subject prefix (`acc-cost`, `tax-cost`), `aliases`로 검색 흡수 |
| 빌더가 잘못된 엣지 양산 (false positive) | edges.jsonl에 `evidence` 필드. 사람이 검토 가능. `--dry-run` 플래그 |
| RAG 청크 수정 시 엣지 stale | 빌더는 idempotent. pre-commit 훅에서 재실행 (후속 작업) |
| LaTeX/수식이 term name에 들어감 | 스키마에서 LaTeX 금지. `formula` 필드만 텍스트 허용. 매칭은 평문 only |
| 용어 수 200+ 시 빌더 느려짐 | 단순 substring 매칭 + dict lookup → O(n×m) 미만. 200×40 청크 = 8k 비교, ms 단위 |

---

## 9. Testing Strategy

`tests/test_term_graph.py` (신규, TDD):
1. `term.schema.json` 유효성 — 잘못된 term JSON은 fail
2. 빌더 결정론 — 동일 입력 2회 실행 → 같은 edges.jsonl
3. `expand_query` — "유효이자율" 입력 → "effective-interest-rate" term + aliases 포함 토큰 반환
4. `search.retrieve` 회귀 — 기존 13개 청크 + 새 term 0개 상태에서 점수 변동 없음
5. **Red-Green**: term 1개 추가 → 관련 청크 검색 점수 상승 확인 → term 제거 → 점수 원복

L1 게이트:
- `python -m pytest tests/test_term_graph.py -v` → 0 failures
- `python scripts/build_term_graph.py --dry-run` → exit 0
- `python -m json.tool` 으로 모든 seed JSON 유효성

---

## 10. Phase Breakdown (구현 순서)

**Phase 1 — Schema only** (T1, ~10분)
- `term.schema.json` 작성
- `term_edge.schema.json` 작성
- README에 추가
- 검증: schema valid, 빈 seed로 시작

**Phase 2 — Seed 시드 (15개)** (T2, ~30분)
- 가장 어렵고 자주 나오는 15개 선정 (4과목 균등):
  - accounting: 상각후원가, 유효이자율, 기대신용손실, 이연법인세, 충당부채
  - tax: 종합과세, 분리과세, 필요경비, 의제매입세액
  - business(원가): 표준원가, 결합원가, 활동기준원가
  - business(재무): WACC, MM 명제, 옵션 델타
- 각 term에 confusable_with 1-2개 명시
- review_status: ai_draft

**Phase 3 — Builder** (T2, ~30분)
- `scripts/build_term_graph.py` 작성
- 단위 테스트 + 결정론 검증
- edges.jsonl 첫 생성

**Phase 4 — Search 통합** (T2, ~20분)
- `term_index.py` 작성
- `search.py` 최소 수정 + 회귀 테스트
- benchmark에서 변화 측정

**Phase 5 — UI 후속** (별도 세션)
- prototype에서 단어 클릭 → 정의 + 관련 문제 사이드패널

---

## 11. Non-Goals (이번 작업 제외)

- 임베딩 기반 시맨틱 검색 (현재 키워드 매칭 유지)
- 자동 정의 생성 (LLM이 term draft 작성은 별도 작업, 이번엔 schema/builder만)
- 200개 풀 시드 (15개 부트스트랩만, 나머지는 점진적)
- prototype UI 변경

---

## 12. Open Questions

1. **15개 부트스트랩 용어 선정** — 위 목록으로 진행할지, 다른 우선순위가 있는지?
2. **edges.jsonl 커밋 여부** — 빌더가 결정론적이지만 diff 가독성 위해 커밋 권장. 동의?
3. **prototype 연동 범위** — 이번 작업은 data + Python 레이어까지. UI는 후속 세션. 맞는지?

---

## 13. Self-Review (4축)

- ✅ Placeholder: TBD/모호 표현 없음 (15개 부트스트랩 명시)
- ✅ Internal consistency: 스키마 ↔ 빌더 ↔ 검색 인터페이스 일치
- ✅ Scope: data + Python 레이어로 한정. UI 제외 명시
- ✅ Ambiguity: term_id 충돌(과목별 동음이의)을 prefix로 명시 해결

---

## Next

사용자 검토 후 Phase 1부터 시작. 변경 요청 시 해당 섹션부터 재진행.
