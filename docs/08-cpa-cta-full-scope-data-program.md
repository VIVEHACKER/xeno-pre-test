# CPA/CTA 전 과목 데이터 프로그램

## 전제

"세상에 존재하는 모든 데이터"를 원문 그대로 흡수하는 방식은 실행도 불가능하고 제품 리스크도 크다. 대신 전 과목을 빠짐없이 커버하는 지식 지도와, 데이터별 권리 상태를 분리한 적재 체계를 만든다.

목표는 다음이다.

```text
CPA/CTA 전 과목
→ 공식 범위
→ 개념 노드
→ 기출/정답/통계
→ 법령/기준서
→ 합격수기/인터뷰
→ 문제풀이 지능
→ 사용자 풀이 로그
→ 개인별 합격 전략
```

## 추가된 저장소

### 전 과목 온톨로지

```text
data/seeds/exam_ontology.json
```

CPA 1차/2차, CTA 1차/2차 전 과목을 `exam_subjects`와 `knowledge_nodes`로 적재한다.

### 수집 타깃 레지스트리

```text
data/seeds/acquisition_targets.csv
```

데이터를 아래 권리 상태로 분리한다.

- `metadata_only`: 메타데이터만 사용
- `metadata_and_notice_text`: 공식 공고/안내문 분석
- `official_download_check_required`: 공식 다운로드 가능하더라도 재배포 전 확인 필요
- `public_law_text_with_attribution`: 법령 출처 표시 필요
- `rights_check_required`: 기준서/전문자료 이용조건 확인 필요
- `permission_required`: 학원/블로그/수기 원문 허락 필요
- `license_required`: 교재/강의/모의고사 권리 확보 필요
- `user_consent_required`: 사용자 로그 동의 필요

## DB 테이블

### exam_subjects

CPA/CTA 시험의 공식 과목 단위다.

예:

- CPA 1차 경영학
- CPA 1차 경제원론
- CPA 1차 기업법
- CPA 1차 세법개론
- CPA 1차 회계학
- CPA 2차 세법, 재무관리, 회계감사, 원가회계, 재무회계
- CTA 1차 재정학, 세법학개론, 회계학개론, 선택법
- CTA 2차 회계학 1부, 회계학 2부, 세법학 1부, 세법학 2부

### knowledge_nodes

과목 안의 단원/개념 지도다.

예:

- 재무회계 → 금융자산 → 상각후원가
- 세법 → 법인세 → 익금/손금
- 세법학 2부 → 지방세법/조세특례제한법
- 회계감사 → 감사위험/중요성

### acquisition_targets

실제 데이터를 어디서 어떤 방식으로 가져올지 관리한다.

예:

- 금융위원회 CPA 시행공고
- 금융감독원 공인회계사시험 포털
- Q-Net 세무사 시행공고
- Q-Net 세무사 기출/정답/통계
- 국가법령정보센터
- 국세법령정보시스템
- 한국회계기준원
- 금융감독원 DART
- 합격자 인터뷰
- 사용자 풀이 로그
- 권리 확보 교재/강의

## 실행

```powershell
python scripts/cpa_data_pipeline.py ontology stats
```

전체 재적재:

```powershell
python scripts/cpa_data_pipeline.py all
```

## 공식 기준

- CPA: 금융위원회 2026년도 제61회 공인회계사시험 시행계획 공고
- CTA: Q-Net 2026년도 제63회 세무사 자격시험 시행계획 공고

이후 연도별 공고가 바뀌면 `exam_ontology.json`의 `version`, 과목명, 출제범위, 시험시간, 배점을 갱신한다.

## 중요한 운영 원칙

1. 공식 공고와 법령은 기준 데이터다.
2. 기출문제와 정답은 권리 상태를 확인하고, 원문 재배포보다 문제 지능 메타데이터를 우선한다.
3. 교재, 강의, 모의고사, 학원 해설은 권리 확보 전 학습/저장/재배포하지 않는다.
4. 합격수기는 원문 저장보다 전략 신호와 근거 앵커를 저장한다.
5. 사용자 학습 로그는 동의 기반으로만 쌓는다.
6. 최종 자산은 원문 더미가 아니라 `개념-문제-풀이전략-오답-합격규칙` 그래프다.
