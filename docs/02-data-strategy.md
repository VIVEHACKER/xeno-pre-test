# 데이터 전략

## 1. 데이터의 세 층

### 1.1 명시지 데이터

공식적으로 확인 가능하거나 문서화된 지식이다.

- 시험 시행계획
- 과목 범위
- 기출문제와 정답
- 회계기준
- 세법 조문과 개정사항
- 모의고사 점수 분포
- 합격선과 경쟁률

명시지는 정확성과 버전 관리가 중요하다. 특히 세법은 적용연도, 개정일, 시행일을 분리해야 한다.

### 1.2 문제풀이 지식 데이터

AI와 전문가가 실제 문제를 풀면서 남기는 풀이 데이터다.

- 어떤 개념을 알아야 하는가
- 문제를 어떤 순서로 읽어야 하는가
- 계산은 어디서 시작해야 하는가
- 시험장에서 몇 초 이상 붙잡으면 위험한가
- 어떤 조건이 함정인가
- 어떤 선택지가 매력적인 오답인가
- 같은 개념을 어떻게 변형할 수 있는가

이 데이터가 제품의 핵심 자산이다.

### 1.3 합격 전략 데이터

합격수기와 인터뷰에서 추출한 행동 규칙이다.

- 공부 순서
- 회독 전환 기준
- 문제풀이 진입 시점
- 과목별 버림 전략
- 모의고사 이후 복구 전략
- 시험 직전 압축 전략
- 불합격 패턴

## 2. 핵심 엔티티

### 2.1 Problem

시험에 출제된 문제 또는 내부 변형 문제다.

주요 속성:

- exam_year
- subject
- unit
- concept_tags
- difficulty
- expected_time_seconds
- source_type
- rights_status

### 2.2 Problem Intelligence

문제를 푸는 데 필요한 사고 과정을 구조화한 데이터다.

주요 속성:

- required_concepts
- solving_entry_point
- solving_steps
- trap_patterns
- discard_rule
- variant_axes
- mistake_diagnosis

### 2.3 Success Story

공개 합격수기 또는 인터뷰를 구조화한 데이터다.

주요 속성:

- candidate_profile
- study_timeline
- subject_strategy
- decision_rules
- failure_avoidance
- confidence
- source_url

### 2.4 User State

사용자의 현재 합격 리스크를 판단하기 위한 상태다.

주요 속성:

- target_exam_date
- available_hours_per_day
- current_stage
- subject_scores
- concept_mastery
- recent_mistakes
- time_pressure_index
- consistency_index

### 2.5 Strategy Prescription

사용자에게 실제로 내려가는 공부 처방이다.

주요 속성:

- diagnosis
- weekly_goal
- daily_tasks
- concepts_to_review
- problems_to_solve
- problems_to_skip
- verification_metric

## 3. 데이터 품질 원칙

1. 원문보다 구조화 데이터가 중요하다.
2. AI가 만든 태그는 사람 검수 상태를 반드시 가진다.
3. 합격수기에서 나온 주장은 단일 사례와 반복 패턴을 구분한다.
4. 세법 데이터는 적용연도 없이 저장하지 않는다.
5. 전략 규칙은 항상 적용 조건과 예외 조건을 가진다.

## 4. 점진적 데이터 구축

### 1단계

- 기출 문제 메타데이터
- 문제별 개념 태그
- 합격수기 요약

### 2단계

- 풀이 순서
- 시간 전략
- 오답 원인
- 변형 포인트

### 3단계

- 사용자 풀이 로그
- 전략 수행률
- 점수 변화
- 개인별 성장 곡선

### 4단계

- 전략 추천 모델
- 합격 리스크 모델
- 사용자 유형별 공부 처방 자동화
