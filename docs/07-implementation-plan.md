# 구현 계획

## 1. 검증 목표

이 MVP는 합격 가능성을 측정하는 시스템이 아니라, **처방 엔진이 동작한다는 것**을 입증하는 시스템이다. 다음 한 문장이 성립해야 한다.

> 사용자 상태(과목별 정답률, 시간 초과율, 남은 기간, 단계)를 입력하면, 결정론적 규칙 엔진이 근거 데이터를 첨부한 처방을 산출한다.

성공 기준은 출제 적중률이나 점수 향상이 아니다. 다음 3가지다.

1. 동일한 사용자 상태에 대해 항상 동일한 처방이 나온다(결정론).
2. 모든 처방 항목에 `evidence_refs`가 붙어 어떤 문제/수기/규칙에서 나왔는지 역추적된다.
3. 사용자 상태가 변하면 처방이 의미 있게 달라진다(처방의 민감도가 0이 아니다).

## 2. 기술 스택과 선택 근거

MVP에서 끝내지 않고 고도화로 이어지는 경로를 우선한다. 단일 PC 운영을 견디면서, 사용자가 늘었을 때 갈아엎지 않아도 되는 선택을 한다.

| 영역 | MVP | 고도화 경로 | 선택 이유 |
|------|-----|--------------|-----------|
| 백엔드 | Python 3.11 + FastAPI | 동일 | LLM 호출, 본문 추출, 스키마 검증 라이브러리가 풍부하고 한국어 처리 부담이 적다 |
| 저장소 | SQLite (sqlite3 표준 라이브러리) | Postgres | 06번 데이터 파이프라인이 이미 sqlite3 스택을 채택해 동작 중. 무거운 ORM 없이도 충분히 동작. 고도화 시점에 SQLAlchemy 도입과 Postgres 마이그레이션을 동시에 진행한다 |
| 데이터 표현 | JSON 파일(seed/sample) + JSON Schema 검증 | 동일 | 사용자 입출력 인터페이스와 LLM 출력 검증 모두 JSON Schema 단일 진실로 통일 |
| 검증 | jsonschema 라이브러리 | 동일 | 입출력 경계에서 강제 |
| 프론트엔드 | 기존 정적 HTML + fetch | Next.js | UI 골격을 유지한 채 API 연결만으로 동적화 가능 |
| LLM | Claude API (Anthropic SDK) | 동일, prompt caching 적용 | 한국어 추출/구조화 품질이 안정적, 캐시로 비용 통제 |
| 본문 추출 | 06번 파이프라인의 urllib + robotparser (또는 jina-reader MCP) | 동일 | 이미 합법성 체크 + robots.txt 준수 동작 |
| 인증 | 단일 사용자(생략) | OAuth + 다중 사용자 | MVP는 처방 엔진 검증에 집중 |
| 작업 오케스트레이션 | python 스크립트 + Makefile | Prefect 또는 Airflow | 초기 데이터 파이프라인은 단순 cron으로 충분 |

`06-data-warehouse-and-pipeline.md`의 데이터 적재 트랙(sources → documents → extracted_signals → strategy_rules)이 이미 동작한다. 이 문서는 그 트랙 위에 **처방 엔진 트랙**(problem_intelligence → user_state → prescription)을 얹는 계획이다. 두 트랙은 `strategy_rules` 테이블(SQL)과 `decision_rule.schema.json`(JSON)에서 만난다. decision_rule 스키마의 필드는 strategy_rules 테이블 컬럼과 일대일 호환되도록 설계한다.

## 3. 마일스톤

데이터 트랙과 코드 트랙을 분리해 병렬로 진행한다. 둘 다 M3에서 통합 검증된다.

### M1 — 데이터 인프라 (1주차)

- 누락 스키마 추가
  - `prescription.schema.json`: diagnosis, weekly_goal, daily_tasks, evidence_refs, triggered_rule_keys
  - `decision_rule.schema.json`: rule_key, rule_name, condition_text, action_text, exception_text, source_signal_count, confidence, review_status (06번 strategy_rules 테이블 컬럼과 호환)
  - `mistake_log.schema.json`: 사용자 풀이 로그용 (problem_id, mistake_categories, time_seconds, attempt_at)
- `cpa_first/` Python 패키지 골격 생성 (06번 `scripts/cpa_data_pipeline.py`는 그대로 유지, 패키지는 처방 엔진 트랙용)
- jsonschema 기반 검증기 + 파일명 자동 라우팅
- SQLite 스키마는 06번 파이프라인이 이미 생성. 처방 엔진 트랙용 추가 테이블(`problem_intelligence`, `user_states`, `prescriptions`)은 M2에서 추가

검증: `python -m cpa_first.cli.validate data/sample/*.json`이 0 에러로 통과.

### M2 — 시드 데이터 + 처방 엔진 (2~3주차)

- 시드 데이터 수동 입력 (LLM 초안 + 사람 검수)
  - 회계학 문제 지능 10건
  - 세법 문제 지능 10건
  - 공개 합격수기에서 추출한 의사결정 규칙 20건
  - 사용자 상태 샘플 5건 (단계별)
- 결정론적 처방 엔진 (`cpa_first/engine/`)
  - 입력: UserState → 출력: Prescription
  - PRD §4.5 importance_score 가중합
  - PRD §4.6 risk_score 누적
  - 규칙 매칭: condition 평가기(간단한 AST 또는 jq-like)
  - 모든 처방 항목에 triggered_rules, evidence_refs 첨부
- 단위 테스트: 시드 사용자 상태별 처방 스냅샷 80%+ 커버리지

검증: 동일 입력→동일 출력. 입력 변동 시 처방 변동. 사람이 읽었을 때 5건 중 4건 이상이 "이해되는" 처방.

### M3 — API + 동적 프론트엔드 통합 (4주차)

- FastAPI 엔드포인트
  - `POST /diagnose`: 진단 입력→UserState 저장
  - `GET /prescription`: 최신 처방 조회
  - `GET /problems/:id`: 문제 지능 카드 조회
  - `GET /evidence/:ref`: 처방 근거 추적
- 기존 `prototype/app.js`를 fetch 기반으로 재작성 (UI는 유지)
- 단일 사용자 가정, 인증 생략
- evidence 패널: 처방 카드 클릭 시 어느 규칙/수기/문제가 근거인지 표시

검증: 진단 입력→처방 표시→근거 클릭→소스 도달까지 End-to-end 동작.

### M4 — 데이터 자산 확장 (5~7주차, M3과 일부 병렬)

- 합격수기 수집 파이프라인
  - URL 등록 → jina-reader 본문 추출 → 개인정보 제거 → LLM 구조화 추출 → 검수 큐
  - 원문은 raw zone, 구조화 결과만 warehouse로 승격
  - 권리 상태가 불명확하면 승격 차단
- LLM 보조 문제 지능 태깅 도구
  - 문제 입력 → LLM 초안 → JSON 스키마 검증 → 사람 검수 폼
- 검수 UI (FastAPI + Jinja 또는 간단한 admin)
- 데이터 목표
  - 회계학 50문항, 세법 50문항
  - 공개 합격수기 50건에서 의사결정 규칙 80개
  - 합격자 인터뷰 3명 (인터뷰 자체는 M3 이후 모집 시작)

검증: 검수자가 LLM 초안을 보고 5분 안에 수정/승인 결정 가능. 거부율 30% 이하면 LLM 프롬프트 안정화로 판단.

### M5 — 학습 루프 검증 (8주차)

- 사용자 풀이 로그 수집 → user_state 자동 업데이트
- 처방 수행률 추적
- 한 명의 베타 사용자가 1주일 운영 → 재진단 → 처방 변화 확인
- 회고 + 다음 단계 결정

검증: 베타 사용자가 처방을 "그대로 따라할 만하다"고 평가. 1주일 후 user_state의 정답률/시간 초과율 변화가 측정 가능.

## 4. 디렉터리 구조 (목표)

```
all of me/
  cpa_first/                 # Python 패키지
    __init__.py
    schemas/                 # pydantic 모델 (JSON Schema와 미러)
    storage/                 # SQLAlchemy + JSONL repository
    engine/                  # 처방 엔진 (rules, scoring, prescription)
    ingestion/               # 합격수기 수집 파이프라인
    tagging/                 # LLM 보조 문제 태깅
    api/                     # FastAPI 앱
    cli/                     # 검증/시드 입력 CLI
  data/
    schemas/                 # JSON Schema (기존 + 추가)
    sample/                  # 검증용 샘플
    seeds/                   # 시드 데이터 (커밋 대상)
    warehouse/               # 운영 데이터 (gitignore, 백업 별도)
    raw/                     # 수기 원문 (재배포 금지, gitignore)
  prototype/                 # 기존 HTML/CSS/JS (점진적으로 fetch 기반화)
  docs/                      # 기획 문서 (현재 위치)
  tests/                     # pytest
  pyproject.toml
  Makefile                   # validate, seed, test, run
```

## 5. 의존성과 리스크

| 항목 | 리스크 | 완화 |
|------|--------|------|
| 합격수기 권리 | 원문 재배포 시 법적 위험 | warehouse는 구조화 데이터만, raw는 분리·내부 전용 |
| 기출 원문 | 출판사 권리 | MVP는 합법적으로 확보 가능한 메타데이터/구조화 데이터만, 원문은 사용자 본인 입력 기준으로 우회 |
| 세법 적용연도 | 연도가 빠지면 정확성 붕괴 | 스키마에서 `applicable_year` 필수화 |
| LLM 환각 | 잘못된 풀이 데이터가 흘러들어감 | 모든 LLM 출력은 `review_status: ai_draft`로 격리, 검수 통과 전 처방에 미사용 |
| 데이터 양 부족 | 처방이 무의미하게 일반론 | M2 시드만으로도 5명 단계별 시나리오를 커버하도록 시나리오 우선 설계 |
| 단일 사용자 가정 | 다중 사용자 전환 시 비용 | DB 모델에 `user_id` 컬럼은 처음부터 포함, 인증 레이어만 후속 추가 |
| 비용 통제 | LLM 호출 폭증 | prompt caching, 검수 후 결과 캐싱, 재실행 시 diff만 호출 |

## 6. 검증 지표 (시스템)

- 스키마 검증 통과율: 입력 데이터 100%
- 처방 결정론성: 동일 입력 100회 → 100회 동일 출력
- 처방 민감도: 단계 전환(post_lecture→objective_entry) 시 처방 항목 ≥ 50% 변화
- 근거 추적 가능성: 처방의 모든 항목에 evidence_refs ≥ 1
- 시드 검수 통과 비율: LLM 초안 검수 1주차 70% 이상

## 7. 8주 일정

| 주차 | 코드 트랙 | 데이터 트랙 |
|------|-----------|-------------|
| 1 | M1 데이터 인프라 | 시드 시나리오 5개 작성 |
| 2 | M2 엔진 코어 | 회계 5문항, 수기 5건 |
| 3 | M2 엔진 완성 + 테스트 | 회계 10/세법 10, 규칙 20 |
| 4 | M3 API + 프론트엔드 | 시드 검수 1차 |
| 5 | M4 수집 파이프라인 | 회계 30/세법 30, 수기 30 |
| 6 | M4 태깅 도구 + 검수 UI | 회계 50/세법 50, 수기 50 |
| 7 | M4 마무리, 베타 운영 준비 | 인터뷰 3명 진행 |
| 8 | M5 학습 루프 검증 + 회고 | 데이터 정리, 다음 시즌 백로그 |

## 8. 고도화 로드맵 (MVP 이후)

| 영역 | 도입 시점 | 내용 |
|------|-----------|------|
| 가중치 학습 | 사용자 100명 또는 처방 로그 1만건 이상 | importance_score 가중치를 사용자 응답률로 학습 |
| 합격 리스크 모델 | 결과 데이터 1시즌 누적 후 | 베이지안 또는 생존분석 기반, 단 "확률" 표현은 PRD §6 따라 신중하게 |
| 인증/다중 사용자 | 베타 5명 안정 후 | OAuth + Postgres 마이그레이션 |
| 모바일 | 다중 사용자 검증 이후 | PWA로 시작, 필요 시 React Native |
| 합격자 매칭 추천 | 인터뷰 30건 이상 누적 후 | 사용자 프로파일 ↔ 합격자 프로파일 유사도 기반 |
| 자동 개정 추적 | 매년 세법 개정안 발표 시점 | 조문 diff → applicable_year 분기 자동화 |

## 9. 명시적으로 배제

이 계획은 다음을 다루지 않는다. 비용/범위 통제 목적.

- 2차 답안 채점
- 강의/교재 마켓플레이스
- 무제한 챗봇 질의응답
- CTA 동시 출시
- 실시간 커뮤니티
- "합격 보장" 마케팅 표현

## 10. 다음 액션

이 문서 승인 후 M1을 시작한다. 첫 작업은 다음 3가지다.

1. `pyproject.toml` + Python 패키지 골격 생성
2. `prescription.schema.json`, `decision_rule.schema.json`, `mistake_log.schema.json` 작성
3. `cpa_first/cli/validate.py` 작성 후 기존 샘플로 통과 확인
