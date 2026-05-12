# CPA First

CPA 1차 회계학/세법개론을 시작점으로 하는 합격 운영체계 기획 산출물입니다.

이 프로젝트의 방향은 단순 기출 통계가 아닙니다. 문제를 실제로 푸는 과정에서 필요한 개념, 풀이 순서, 시간 판단, 함정, 변형 가능성을 구조화하고, 공개 합격수기와 합격자 인터뷰에서 뽑은 암묵지를 사용자 상태에 맞는 공부 처방으로 바꾸는 것입니다.

## 산출물

- [제품 요구사항 문서](docs/01-prd-cpa-first.md)
- [데이터 전략](docs/02-data-strategy.md)
- [합격수기 크롤링 및 인터뷰 설계](docs/03-success-story-and-interview-system.md)
- [전략 엔진 설계](docs/04-strategy-engine.md)
- [문제풀이 지능 프로토콜](docs/05-problem-solving-intelligence.md)
- [실제 데이터 적재 파이프라인](docs/06-data-warehouse-and-pipeline.md)
- [구현 계획](docs/07-implementation-plan.md)
- [CPA/CTA 전 과목 데이터 프로그램](docs/08-cpa-cta-full-scope-data-program.md)
- [기출문제/정답/해설 자산 적재](docs/09-past-exam-and-explanation-assets.md)
- [과목별 튜토리얼과 다중 풀이 경로](docs/10-subject-tutorials-and-solution-paths.md)
- [문제별 풀이맵](docs/12-problem-solution-maps.md)
- [풀이맵 기반 응시 진단](docs/13-attempt-diagnosis.md)
- [데이터 소스 레지스트리](data/source_registry.yaml)
- [초기 원천 URL 시드](data/seeds/cpa_success_sources.csv)
- [CPA/CTA 전 과목 온톨로지](data/seeds/exam_ontology.json)
- [수집 타깃 레지스트리](data/seeds/acquisition_targets.csv)
- [기출/정답/해설 자산 시드](data/seeds/past_exam_assets.csv)
- [과목별 튜토리얼 시드](data/seeds/subject_tutorials.json)
- [문제별 풀이맵 프로토타입 데이터](prototype/problem_solution_maps.json)
- [JSON 스키마](data/schemas) (`term.schema.json`, `term_edge.schema.json` 포함 — 용어 지식 그래프)
- [샘플 문제 지능 데이터](data/sample/cpa_problem_intelligence.example.json)
- [정적 MVP 프로토타입](prototype/index.html)

## 프로토타입 실행

### 처방 엔진 + 동적 대시보드 (권장)

`cpa_first` 패키지(M1~M3 결과)는 FastAPI 백엔드와 정적 프론트엔드를 함께 서빙합니다.

처음 한 번 의존성 설치:

```powershell
python -m pip install -e ".[dev]"
```

서버 실행:

```powershell
python -m cpa_first.api.main --host 127.0.0.1 --port 8000
# 또는 console script
cpa-serve --port 8000
```

`http://127.0.0.1:8000`으로 접속하면 진단 입력이 바로 처방 엔진에 연결되고, 처방 카드 아래
"처방 근거" 패널의 각 항목을 클릭하면 의사결정 규칙/문제 지능/사용자 상태 원본을 그대로
조회할 수 있습니다.

엔드포인트:

- `POST /diagnose` — 사용자 상태 입력 → 처방 산출
- `GET /prescription` — 마지막 진단 처방 재조회
- `GET /problems/{problem_id}` — 문제 지능 카드
- `GET /evidence/{ref_type}/{ref_id}` — 근거 추적 (decision_rule / problem_intelligence / user_state)
- `POST /attempts/diagnose` — 선택 보기와 풀이 시간을 풀이맵으로 진단하고 누적
- `GET /attempts` — 누적 응시 진단 로그 조회

### 정적 모드 (백엔드 없이)

```powershell
cd "C:\Users\gidc111\all of me\prototype"
python -m http.server 4173
```

`http://localhost:4173` 접속. 이 모드에서는 백엔드 기록은 남지 않지만,
파이프라인이 만든 `data_manifest.json`, `subject_tutorials.json`, `problem_solution_maps.json`과 로컬 응시 진단 미리보기는 동작합니다.

## 검증

```powershell
python -m cpa_first.cli.validate "data/sample/*.json" "data/seeds/**/*.json"
python -m pytest tests/
```

## 초기 제품 정의

> CPA 1차 회계학/세법개론 수험생에게, 합격일까지 남은 시간과 현재 실력을 기준으로 오늘 풀 문제, 복습할 개념, 버릴 유형, 회독 순서를 결정해주는 AI 합격 코치.

## 데이터 적재

합격수기와 시험 전략 자료는 SQLite에 누적합니다.

```powershell
python scripts/cpa_data_pipeline.py all
```

생성되는 파일:

- `data/warehouse/cpa_first.sqlite`
- `data/warehouse/manifest.json`

CPA/CTA 전 과목 온톨로지만 갱신:

```powershell
python scripts/cpa_data_pipeline.py ontology stats
```

기출/정답/해설 자산 갱신:

```powershell
python scripts/cpa_data_pipeline.py exam-assets stats
```

과목별 튜토리얼/풀이 경로 갱신:

```powershell
python scripts/cpa_data_pipeline.py tutorials stats
```

문제별 풀이-개념 연결맵 갱신:

```powershell
python scripts/cpa_data_pipeline.py problem-solutions stats
```

## 핵심 원칙

1. 기출문제는 통계 대상이 아니라 풀이 지능의 원천이다.
2. 합격수기는 감동문이 아니라 의사결정 규칙 데이터다.
3. AI 해설은 정답 설명이 아니라 사용자의 다음 행동을 바꾸는 진단이어야 한다.
4. 합격확률은 마케팅 문구가 아니라 현재 상태의 리스크 지표로 다뤄야 한다.
