# 평가셋 확장 + 난이도 태깅 설계

> 작성일: 2026-05-12 / 목표: 13건 → 100건, ceiling effect 해소, 변별력 확보
> 결정 근거: 라이브 벤치마크 13/13 = 100% (`data/runtime/benchmark_runs/20260512T010513Z.json`)

## 1. Scope (단일 sub-project)

- evaluation_question 스키마 확장: 난이도 3축 필드 추가
- 단원 분포 설계: 회계 60 + 세법 40 = 100건
- Claude 기반 2-pass 생성 파이프라인: 생성 → 검증 → 저장
- 산출물: `data/seeds/evaluation/*.evaluation_question.json` 87건 추가
- **out-of-scope**: 진짜 기출 변환(B안), RAG A/B 비교(C안), 권리 처리 정책 변경

## 2. Approach 비교 — 선정안: **A2 (배치 생성 + per-question 검증)**

| 안 | 흐름 | 장점 | 단점 |
|---|---|---|---|
| A1 | 1문항씩 생성→검증 (직렬) | 디버깅 쉬움 | 시간 길음 (~30분) |
| **A2** | **5문항 배치 생성 → 각 문항 검증** | **요청 수 ↓, 컨텍스트 공유** | **배치 중 1개 실패 시 재시도** |
| A3 | 한 번에 100건 일괄 생성 | 호출 최소 | 토큰 한도/품질 저하 |

**A2 채택 이유**: claude-opus-4-7 max_tokens=2000으론 5문항이 한계. 검증은 문항별 독립이 합리적(매력적 오답 점검 정밀도).

## 3. Schema 확장 — `evaluation_question.schema.json`

추가 필드 (모두 optional, 기존 13건 호환):

```jsonc
{
  "difficulty": "easy" | "mid" | "hard",           // 3단계 카테고리
  "difficulty_score": 1 | 2 | 3 | 4 | 5,            // 1=trivial, 5=함정+다단계
  "bloom_level": "remember" | "understand" | "apply" | "analyze" | "evaluate",
  "attractor_traps": ["문항이 노린 매력적 오답 종류"]  // 검증 라운드에서 채움
}
```

`difficulty` ↔ `difficulty_score` 매핑: easy=1-2, mid=3, hard=4-5.

## 4. 단원 분포 — 회계 60 + 세법 40

### 회계학 (60건)

| 단원 | 기존 | 추가 | 합 | 출제 빈도 가중치 |
|---|---|---|---|---|
| financial_assets (금융자산) | 1 | 5 | 6 | 高 |
| inventory (재고자산) | 1 | 4 | 5 | 中 |
| tangible_assets (유형자산) | 1 | 5 | 6 | 高 |
| intangible_assets (무형자산) | 0 | 3 | 3 | 中 |
| revenue_recognition (수익인식) | 1 | 4 | 5 | 高 |
| liabilities (부채/충당부채) | 1 | 4 | 5 | 高 |
| equity (자본) | 1 | 3 | 4 | 中 |
| cash_flow (현금흐름표) | 1 | 3 | 4 | 中 |
| cost_management (원가관리) | 1 | 4 | 5 | 中 |
| lease (리스) | 0 | 3 | 3 | 中 |
| income_tax_accounting (법인세회계) | 0 | 3 | 3 | 中 |
| business_combination (사업결합/연결) | 0 | 4 | 4 | 高 |
| financial_instruments (파생/헤지) | 0 | 3 | 3 | 中 |
| eps_diluted (주당이익) | 0 | 2 | 2 | 低 |
| changes_errors (회계변경·오류) | 0 | 2 | 2 | 中 |
| **합계** | **8** | **52** | **60** | |

### 세법개론 (40건)

| 단원 | 기존 | 추가 | 합 | 출제 빈도 가중치 |
|---|---|---|---|---|
| national_tax_basic_act (국세기본법) | 1 | 4 | 5 | 高 |
| income_tax (소득세법) | 2 | 7 | 9 | 高 |
| corporate_tax (법인세법) | 1 | 9 | 10 | 高 |
| vat (부가가치세법) | 1 | 6 | 7 | 高 |
| inheritance_gift_tax (상속세·증여세) | 0 | 3 | 3 | 中 |
| international_tax (국제조세) | 0 | 3 | 3 | 中 |
| local_tax_etc (지방세·기타) | 0 | 3 | 3 | 低 |
| **합계** | **5** | **35** | **40** | |

## 5. 난이도 분포 (전체 100건)

| 난이도 | 비율 | 건수 | 특징 |
|---|---|---|---|
| easy | 25% | 25 | 단일 식·정의 적용 (~60초). bloom: remember/understand |
| mid | 50% | 50 | 2-3단계 계산 또는 조문 해석 (~90초). bloom: apply |
| hard | 25% | 25 | 다단계 계산 + 매력적 오답 + 예외 조항 (~120-150초). bloom: analyze/evaluate |

## 6. 생성 파이프라인

### 6-1. 새 파일

```
cpa_first/eval_gen/
  __init__.py
  generator.py        # 5문항 배치 생성 (genrate_batch)
  validator.py        # 문항별 검증 (validate_question)
  writer.py           # JSON 저장 + ID 발급
  cli.py              # python -m cpa_first.eval_gen.cli --target accounting --unit lease --count 3 --difficulty hard

scripts/
  generate_eval_set.py  # 분포 설계 따라 87건 일괄 생성 (오케스트레이터)
```

### 6-2. 생성 프롬프트 핵심

- system: "당신은 CPA 1차 출제위원이다. K-IFRS 적용연도·세법 적용연도 명시 필수."
- user: 단원 + 난이도 + bloom + 기존 단원 예시 1-2건 → JSON 배열 출력 강제
- 출력 포맷: `{ "questions": [ { evaluation_question 객체 × 5 } ] }`

### 6-3. 검증 프롬프트 핵심

- input: 생성된 문항 1건 (정답 포함)
- 점검: (a) 정답이 실제로 유일한 정답인지, (b) 오답 보기가 매력적 오답 패턴을 따르는지, (c) 조문/기준 인용 정확한지, (d) 난이도 태그가 실제 풀이 단계 수와 일치하는지
- 출력: `{ "verdict": "approve|revise|reject", "issues": [], "attractor_traps": [], "revised": {...optional...} }`

### 6-4. 재시도 정책

- 생성 실패 (JSON parse 실패, 필드 결손) → 1회 재시도 후 skip + 로그
- 검증 verdict=reject → 1회 재생성 후 reject 유지 시 skip
- 검증 verdict=revise → `revised` 채택, `review_status: ai_draft_revised`
- 최종 산출: 목표 100건 중 reject/skip 만큼 부족할 수 있음 → 보고

## 7. 비용 추정

- 100문항 × (생성 1/5 batch + 검증 1) = 20 batch + 100 검증 = 120 호출
- 토큰: 생성 batch ~3K input + 6K output × 20 = 180K tok. 검증 ~2K input + 1K output × 100 = 300K tok. 합 ~500K tok.
- claude-opus-4-7 가격(추정 $15/M input, $75/M output): 입력 ~$3, 출력 ~$15 → **합 약 $15-20**
- 실행 시간: 2-pass × 100 ≈ 15-30분 (rate limit 의존)

## 8. 권리·검토 상태

- `rights_status: "synthetic_seed"` (자체 생성, 권리 안전)
- `review_status: "ai_draft"` (검증 통과한 것은 `ai_draft_verified` 추가 enum 후보 — 사용자 결정 필요)
- 기존 13건의 `expert_reviewed` 상태는 보존

## 9. Implementation Plan (단계별 게이트)

| 단계 | 산출 | 게이트 |
|---|---|---|
| 1. Schema 확장 | `evaluation_question.schema.json` v2 | `python -m cpa_first.cli.validate` 13건 모두 PASS |
| 2. 생성/검증 모듈 | `cpa_first/eval_gen/*` + 단위 테스트 | mock LLM으로 RED→GREEN→테스트 통과 |
| 3. dry-run | --target=accounting --unit=lease --count=2 (live) | 2건 생성+검증, 사용자 샘플 검토 |
| 4. 일괄 실행 | `scripts/generate_eval_set.py` | 87건 신규 + 분포 보고서 |
| 5. 재벤치마크 | `python -m cpa_first.benchmark.runner --mode live` | 100건 정답률, 난이도별 정답률 |

## 10. Edge Cases

- 세법 적용연도: 2026년 기준. `applicable_year: 2026` 강제. 개정사항 누락 시 attractor_trap에 기록.
- 회계: K-IFRS 기준. 일반기업회계기준 GAAP는 별도 단원이 아니므로 생성 금지.
- ID 충돌: `cpa1-eval-{subject}-NNN` 시퀀스. 기존 max + 1부터. accounting-009~, tax-006~.
- 매력적 오답 0개 → revise. 4지선다 중 명백한 오답만 있으면 변별력 없음.
- 단일 정답 보장: 검증 라운드에서 두 보기가 둘 다 옳다고 판단되면 reject.

## 11. Validation Plan (Self-Review)

- ✅ Placeholder scan: TBD 없음. 모든 수치 확정.
- ✅ Internal consistency: 분포 합계 검증 (60+40=100, 25+50+25=100)
- ✅ Scope check: 단일 PR 범위. RAG는 out-of-scope.
- ✅ Ambiguity check: `review_status` 신규 enum 1개 추가 (`ai_draft_verified`) — 사용자 승인 필요

## 12. User Review Gate

이 문서 승인 후 단계 1부터 진행. 변경 요청 시 해당 섹션부터 재진행.

**사용자 결정 필요 항목**:
- (Q1) `review_status` enum에 `ai_draft_verified` 추가해도 되나? (검증 통과한 ai_draft 표시용)
- (Q2) 비용 $15-20 GO?
- (Q3) dry-run(2건) 먼저 보고 결정 vs 바로 100건 일괄?
