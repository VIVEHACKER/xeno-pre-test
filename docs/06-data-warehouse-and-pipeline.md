# 실제 데이터 적재 파이프라인

## 핵심 변경

합격수기를 "수집해서 읽는" 방식은 제품 자산이 되지 않는다. 이제 데이터는 아래 순서로 누적된다.

```text
원천 URL
→ fetch 상태
→ 본문 해시와 내부 분석 텍스트
→ 추출 신호
→ 전략 규칙
→ 검수 상태
→ 사용자 처방 엔진
```

## 저장소

SQLite DB:

```text
data/warehouse/cpa_first.sqlite
```

상태 요약:

```text
data/warehouse/manifest.json
```

초기 원천 목록:

```text
data/seeds/cpa_success_sources.csv
```

## 테이블

### sources

공개 합격수기, 시험 공고, 통계 후보 등 모든 원천 URL을 저장한다.

중요 필드:

- url
- title
- domain
- source_type
- exam
- rights_policy
- collection_status

### documents

실제 fetch 결과를 저장한다.

중요 필드:

- source_id
- robots_allowed
- http_status
- content_hash
- content_length
- normalized_text_hash
- normalized_text
- fetch_error

`normalized_text`는 내부 분석용이다. 서비스 화면에 원문을 그대로 노출하지 않는다.

### extracted_signals

수기 본문에서 추출한 학습 신호다.

예:

- 객관식 전환 시점
- 기출 회독 목적
- 세법 말문제 휘발 관리
- 회계/세법 집중 전략
- 시험장 시간 운영 신호

원문 문장을 길게 저장하지 않고 `evidence_anchor`에 해시와 키워드 앵커를 저장한다.

### strategy_rules

여러 신호를 묶어 전략 엔진이 사용할 수 있는 규칙으로 만든다.

예:

```text
rule_name: 객관식 전환 조건
condition: 기본강의 이후 객관식 관련 신호가 반복되고 사용자가 문제 전환이 늦은 상태
action: 신규 강의 확장을 제한하고 객관식 세트와 오답 원인 분류를 주간 처방에 포함
exception: 핵심 개념 정답률 40% 미만이면 개념 복구 우선
```

## 실행

```powershell
python scripts/cpa_data_pipeline.py all
```

단계별 실행:

```powershell
python scripts/cpa_data_pipeline.py init
python scripts/cpa_data_pipeline.py seed
python scripts/cpa_data_pipeline.py fetch --limit 5
python scripts/cpa_data_pipeline.py extract
python scripts/cpa_data_pipeline.py rules
python scripts/cpa_data_pipeline.py stats
```

## 운영 원칙

1. 원천은 URL 단위로 등록한다.
2. fetch 성공/실패를 모두 DB에 남긴다.
3. 원문은 내부 분석용으로만 쓰고 사용자 화면에는 전략 신호를 제공한다.
4. 모든 추출 신호는 `review_status`를 가진다.
5. 전략 규칙은 source signal count와 confidence를 가진다.
6. 합격자 인터뷰도 같은 스키마에 `source_type = interview`로 들어간다.

## 다음 고도화

- LLM 추출기를 붙여 문장 기반 신호를 더 정밀하게 구조화
- 합격자 인터뷰 녹취록을 같은 DB에 적재
- 문제풀이 지능 데이터와 전략 규칙을 연결
- 사용자 풀이 로그에서 규칙의 실제 효과 측정
