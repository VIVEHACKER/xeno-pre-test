# AI 응시자 + 평가 벤치마크

## 1. 왜 응시자가 필요한가

코치 시스템(M1~M5)의 천장은 AI의 응시 능력에 묶여 있다. problem_intelligence 데이터를 손으로 N건 만들고 멈추면 처방의 깊이도 거기서 멈춘다. AI가 문제를 사람 수준으로 풀어내야:

- problem_intelligence 시드를 "사람 작성 + AI 초안"에서 "AI 자동 + 사람 spot-check"로 전환할 수 있다.
- 매년 시험 직후 새 회차를 자동 분석해 시드를 확장할 수 있다.
- 처방 엔진의 의사결정 규칙도 "어떤 문제 유형에서 통하는가"를 자동 측정할 수 있다.

응시자는 별개 트랙이 아니라 **코치 시스템의 데이터 엔진**이다.

## 2. 가드레일 (06번 권리 정책 그대로)

이 트랙은 새 정책을 만들지 않는다. 06번 가드레일을 그대로 따른다.

- 학원·출판사 해설은 학습/생성에 쓰지 않는다.
- 공식 기출 원문은 평가 입력으로만 쓰고 재배포하지 않는다.
- 자체 생성 모의문제, 공식 조문(K-IFRS·세법), 권리 검토 완료된 사용자 풀이 로그만 학습/생성 자산으로 쓴다.
- 모든 AI 출력은 `evidence_refs`로 근거를 남긴다. 환각은 근거 없는 출력 = 사람 거부 대상으로 분류한다.

## 3. 두 트랙

```
A. 평가 벤치마크 (먼저)
   evaluation_questions → solver → 자동 채점 → 점수 추적

B. 풀이 지능 생성 봇 (그 다음)
   문제 → solver(설명 모드) → problem_intelligence 초안 → 사람 spot-check
```

A부터 가는 이유: 측정 없는 솔버는 향상 방향이 없다. 0점에서 시작해 어디까지 가는지를 측정해야 데이터/프롬프트/도구 어디를 보강할지 결정할 수 있다.

## 4. A. 평가 벤치마크

### 4.1 데이터

- 자체 생성 객관식 모의 문제 (권리 가드레일에 안전한 자체 자산)
- 각 문항: `evaluation_question.schema.json` 형식
- 필수 필드: question_id, subject, unit, stem, choices, correct_choice, explanation, rights_status
- 시드 위치: `data/seeds/evaluation/<subject>/*.evaluation_question.json`

### 4.2 채점

객관식은 정답 일치. 다지선다 보기 인덱스 매칭.

서답형(향후): LLM-as-judge로 평가하되 평가 모델은 응시 모델과 분리. 사람 spot-check 비율 30%+ 유지.

### 4.3 출력

벤치마크 1회 실행마다 다음을 남긴다.

- `data/runtime/benchmark_runs/<run_id>.json`
  - run_id, started_at, finished_at
  - solver_mode, model_name
  - 과목별 정답률
  - 문항별 결과 (정답 여부 + solver 출력 + 소요 토큰)
- 합격선 비교 (CPA 1차 회계학 60% / 세법 60% 가정)

## 5. B. 풀이 지능 생성 봇

같은 solver를 "설명 모드"로 호출하면 problem_intelligence 초안을 산출한다.

- 입력: 문제 (원문 또는 자체 생성)
- 출력: problem_intelligence.schema.json 호환 JSON 초안
- review_status: ai_draft 로 강제 (사람 검수 전 사용 불가)
- 사람 검수자: 5분 안에 spot-check 가능한 출력 포맷이 목표

거부율(검수자가 ai_draft를 rejected로 보내는 비율)이 30% 이하로 떨어지면 자동화 변곡점.

## 6. Solver 구성

```
입력 (문제 + 과목/단원)
  ↓
시스템 프롬프트 (역할, 출력 포맷, 권리/환각 가이드라인)
  ↓
RAG 인덱스 조회 (K-IFRS / 세법 조문 / 자체 해설)
  ↓
[1회전] 식 잡기 — solving_entry_point + solving_steps 초안
  ↓
Tool 호출 (계산기 / 매기 누적 표 / 날짜 산출)
  ↓
[2회전] 검산 + 답 확정 — 정답 + 풀이 지능 출력
  ↓
응답 (정답 + 풀이 + evidence_refs)
```

### 6.1 LLM

- 1차: Anthropic Claude (한국어 + 긴 조문 처리 안정)
- 비교용: OpenAI GPT-4 (영문 USCPA 통과 사례 있음)
- 평가에서 양쪽 모두 측정

### 6.2 RAG 인덱스 (점진적)

- v0: 인덱스 없음. 모델 closed-book 점수가 베이스라인.
- v1: K-IFRS 핵심 챕터 + 세법 조문 (적용연도 분기 필수). 자체 요약본만 인덱싱(권리물 본문 인덱싱 금지).
- v2: 자체 생성 해설 + 검수 완료된 problem_intelligence.

### 6.3 Tool

- `calculator`: 사칙연산 + 거듭제곱 + 합/평균
- `amortization_table`: 매기 이자/원금 누적 표 (현가/유효이자율 문제용)
- `date_diff`: 보유/거주 기간 등 일/월/년 계산
- 모두 Pydantic 검증된 입력. LLM이 임의 코드 실행하지 않도록.

### 6.4 Two-pass 추론

우리 `accounting_two_pass_drill` 규칙의 셀프 적용:

1. 1회전: 식과 풀이 시작점만 잡고 답을 내지 않음.
2. 2회전: 식을 다시 보며 함정/조건 누락/계산 실수 점검. 답 확정.

이 패턴은 회계학 계산형에서 점수가 가장 크게 오르는 운영 전략이다.

### 6.5 모드

- `mock`: API 키 없이 동작. 결정론적 stub 답 반환 (테스트/CI용).
- `live`: Anthropic API 키 필요. 실제 LLM 호출.

환경변수 `CPA_SOLVER_MODE`. 기본 `mock`.

## 7. 단계

| 단계 | 결과물 | 검증 |
|------|---------|------|
| S0 | 설계 문서 + evaluation_question 스키마 + 자체 생성 평가 5건 | jsonschema 통과 |
| S1 | solver 골격 (mock) + benchmark 러너 | 0점이 아니라 mock 답 비율 = 25%로 동작 입증 |
| S2 | solver live 모드 + Claude API 통합 | Claude로 평가 1회 실행, 과목별 점수 기록 |
| S3 | Tool 통합 (calculator/amortization/date_diff) | tool 미사용/사용 비교 점수 |
| S4 | RAG v1 (조문 자체 요약본) | RAG 미사용/사용 비교 점수 |
| S5 | 풀이 지능 생성 봇 (설명 모드) | 검수자 거부율 측정 |

## 8. 합격선

CPA 1차 합격선은 평균 60% + 과목별 40% 이상. 모의 평가에서 다음 목표:

- 단기: 회계 35% / 세법 35% 도달
- 중기: 회계 55% / 세법 55%
- 장기: 두 과목 60%+ 동시 달성

이 수치는 모의 평가셋 기준. 공식 시험 실제 합격선과 동일하지 않다.

## 9. 명시적으로 배제

- 실제 시험장 대리 응시 (불법)
- 권리물 본문 학습/생성
- 합격 보장 표현
- 응시자 모듈이 사용자에게 직접 답을 풀어주는 기능 (코치의 역할은 그대로 "다음 행동" 결정)

## 10. 코치 시스템과의 접점

- problem_intelligence 시드: solver 설명 모드가 초안 생성, 사람 검수, 코치 시스템이 사용
- decision_rule: solver의 풀이 패턴(예: "조건 누락이 잦은 단원")을 분석해 새 의사결정 규칙 후보를 자동 제안
- 처방 검증: 처방을 따른 사용자 vs 안 따른 사용자의 solver-측정 점수 변화 추적
