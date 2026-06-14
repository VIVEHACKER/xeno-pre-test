# 2026-06-11 — 3대 능력 실측 검증 + 학습 루프 구축

질문: **"실제 문제 풀이·제작 능력이 있고, 따라가기만 하면 개념과 풀이력이 자연스럽게 늘
합격 가이드라인을 주는 AI인가?"**

판정(요약): **검증 전 기준으로는 '아니오'** — 두뇌(풀이·제작)는 합격선 위로 실측됐지만,
제품이 그것을 학습자에게 전달하지 못하고 있었다(처방이 풀 문항을 0개 추천, 풀이 AI는
API 미연결, 튜토리얼 미노출). **이번 작업으로 전달 경로를 구축**했고, 남은 한계는 아래에
정직하게 기록한다.

## 1. 풀이 능력 — 실측

| 측정 | 백엔드 | 데이터 | 결과 | 출처 |
|---|---|---|---|---|
| CPA-core 4과목 (실 KMMLU 120문항) | codex | 실기출 유사(공개 벤치) | **95% (114/120)**, RAG-on 세법 100% | 2026-06-codex-capability-baseline.md |
| 세법 로컬 천장 | qwen3.5:27b-int4 | 자체 39문항 | 69.2% (12문항 항상 오답) | tax39-repeat3-summary.json |
| 로컬 최난도 9문항 | codex | 동일 RAG+프롬프트 | **8/9 (88.9%)** — 병목은 지식이 아니라 다단계 계산 | cloud-run-progress.log |
| 라우팅 solver 제품 경로 E2E (과목별 2문항, 세법→codex, 나머지→로컬) | routing | 자체 10문항 | **10/10 (100%)** — 세법 2문항은 로컬 항상-오답군인데 codex가 각 23·39초에 정답. 로컬 과목 문항당 133~372초(연습용 한계) | local-eval-runs/routing-smoke10.json |

**발견·수정한 결함**: `cpa_first/llm.py`의 ollama 어댑터가 `num_ctx`/`num_predict`를 설정하지
않아 제품 경로(라우팅 solver)가 ollama 기본 4k 컨텍스트로 동작 — 벤치마크(16k 명시)와
제품의 정확도가 괴리될 구조였다. 옵션 명시 + env 설정(`CPA_OLLAMA_NUM_CTX` 등)으로 수정.

**합격선 대비**: CPA 1차 합격 기준(평균 60%·과목 40%) 대비 클라우드 백엔드는 전 과목
크게 상회. 로컬 단독은 세법(43.6%→69.2% 천장)이 과락권이므로 라우팅(세법→클라우드)이
운영 전제다.

### 1.1 실제 기출 실측 (2026-06-13 추가) — 합성 천장 우려 해소

**데이터**: 금융감독원 공식(cpa.fss.or.kr) 2026 제61회 1차 기출 PDF를 직접 다운로드·파싱
(`scripts/collect_real_exams.py`, `parse_real_exams.py`). 공식 출처 eval 전용, git 미커밋.
수식이 PDF 폰트 ToUnicode 부재로 PUA 글리프 유실된 문항(주로 경제)은 `math_lossy`로 제외 —
**텍스트로 풀 수 없는 문항이지 모델 한계가 아님**(비전 모델 필요).

codex 백엔드, 164문항(경제 수식유실 제외분 기준). **미해결 5개를 재측정(900초)해 전부
해결** → 보정=유효로 수렴:

| 과목 | 정답률 (2026-06-14 확정) | 진짜 오답 |
|---|---|---|
| business | **100% (25/25)** | 0 |
| **상법(corporate_law)** | **97.5% (39/40)** | 1 |
| accounting | 94.0% (47/50) | 3 |
| economics(수식유실 제외 10문항) | 90.0% (9/10) | 1 |
| tax | 87.2% (34/39) | 5 |
| **전체** | **93.9% (154/164)** | 10 |

> §1.2에서 경제 수식 문항을 비전 복원해 합치면 **2026 전 과목 완전 174/186 = 93.5%**
> (경제 완전 29/32 = 90.6%). 위 표는 수식유실 제외 기준, 이 줄은 수식 포함 완전 기준.

수치 변천(타임아웃·한도 아티팩트 제거 과정):
- **원시 86.6%(142/164)**: 첫 실행 codex 240초 타임아웃에 깎인 하한. 오답 22개 중
  17개가 `chose=-1`(답 추출 실패), 600초 재실행 시 9개 정답 회복 — 타임아웃은 지식
  실패가 아니라 인프라 절단(상법 Q26은 재실행 시 `ANSWER: 3` 정답).
- **확정 93.9%**: 미해결 5개(600초 초과 2 + 사용량 한도 3)를 한도 리셋 후 900초로
  재측정 → 3개 정답(상법 Q30, 경영 Q4·Q7)·2개 진짜 오답(상법 Q40, 경제 Q28). 미해결 0.

**핵심**: 메모리의 "상법 실기출 검증 부재 — 합성 15문항 93%만"이 **실제 상법 기출 40문항
97.5%로 해소**. 합격 기준(평균 60%·과목 40%) 전 과목 크게 상회(최저 세법 87.2%).

### 1.2 경제 수식 문항 비전 복원 (2026-06-14) — 측정 갭 #3 해소

경제 문항의 64%(104문항 중 68개)가 PDF 수식 폰트 ToUnicode 부재로 텍스트 추출 시 수식이
PUA 글리프로 유실(`math_lossy`)돼 위 측정에서 제외됐었다. 이를 **페이지 렌더+비전 전사**로
복원:
- `scripts/render_math_lossy_pages.py`: 해당 페이지를 200dpi PNG로 렌더(mutool).
- 비전 에이전트가 이미지에서 수식을 평문(K^(1/3), 2M/(3P_X+2P_Y), sqrt, min[], 그리스문자)
  으로 전사. 24페이지 병렬 → 2026 후반 5문항 보충 재전사. 총 68문항 복원(스킵 0).
- `scripts/apply_vision_recovery.py`: math_lossy 문항의 stem/보기를 전사본으로 교체,
  **정답키(correct_choice)는 보존**(정답표에서 이미 검증). review_status=vision_recovered.
- 검증: 전사 정확도는 실제 이미지 대조(2025 Q7 위험프리미엄)로 확인 + 정답키 수기 검산
  (2026 Q32 솔로우 균제상태 = 4^(3/2), 2025 Q7 = 64) 일치. 할루시네이션 아님.
- 그림 의존 4문항(필립스/AD-AS 곡선 등)은 그림을 텍스트로 기술해 근사(완벽 복원 한계).

**복원 68문항 codex 실측: 65/68 = 95.6%** (2024 23/23·2025 22/23·2026 20/22, 진짜 오답 3).
이 수치 자체가 복원 품질의 증명 — 전사가 깨졌거나 할루시네이션이면 codex가 ~20%(랜덤)였을
것이나 95.6%가 나왔다(타임아웃 2개는 900초 재측정으로 정답 회복분 포함).

이로써 경제 완전 측정이 가능해졌다:
- **2026 경제 완전(32문항)**: 비-수식 9/10 + 복원 20/22 = **29/32 = 90.6%**.
- **2026 전 과목 완전(수식 포함 186문항)**: 154 + 20 = **174/186 = 93.5%**.

즉 §1.1의 "경제 9문항만"이라는 작은 표본 한계가 해소돼, 경제도 다른 과목과 같은
90% 선임이 확인됐다. 산출물: `real-econ-recovered-{codex,final}.json`.

**발견·수정한 결함**: codex 호출 타임아웃이 240초 하드코딩 → 다단계 계산 문항이 절단됨.

**발견·수정한 결함**: codex 호출 타임아웃이 240초 하드코딩 → 다단계 계산 문항이 절단됨.
`CPA_CODEX_TIMEOUT` env로 조정 가능하게 수정(`cpa_first/llm.py`).

**파싱 검증**: 5개 과목 병렬 적대 검증(PDF 원문 대조). 발견·수정한 파서 결함 —
① 페이지 푸터/번호가 보기⑤에 혼입(헤더/푸터 영역 within_bbox 배제로 해결),
② 우측 컬럼 문항번호가 고정 중앙선 침범해 좌측 stem 오염(페이지별 동적 컬럼 분할선으로 해결),
③ 회계 공유자료 블록(※ N·M번 공통) 유실(블록 분리 후 두 문항에 복원),
④ 세법 계산형의 stem 내 ①~⑤ 자료번호를 보기로 오인(마지막-5 규칙으로 해결).
정답키는 워크플로가 PDF 정답표와 대조해 **4과목 254/254 일치** 확증(①형 컬럼).
전수 오염 스캔 597문항 → 잔존 푸터 오염 2건(세법 의제매입세액 `4/104` 분수, 무해).

**2차 코드리뷰 잔여(정직 기록)**: ⓐ `math_lossy`는 PUA 글리프 치환만 잡고 수식이
공백으로 완전 증발하는 경우는 못 잡는다(false negative). 이 경우 해당 문항이 채점에
포함돼 자료 부족으로 오답 → **점수를 낮추는 방향**이므로 95%는 하한일 수 있음(부풀림 아님).
공격적 휴리스틱은 정상 문항을 제외해 점수를 부풀릴 위험이 커 도입 보류. ⓑ manifest는
연도 단위 덮어쓰기라 부분 실패 시 재실행 전체로 복원 전제. ⓒ `_NOISE_LINE`의 `법` 단독
줄 삭제는 이론적 — 실데이터 보기에 단일자 `법`은 없음. ⓓ 공유블록 분리 시 개행 패딩 추가
(문항 drop 방지). ⓔ 정답표 줄 파싱은 ①형(첫 정답값) 채택 — 정답 PDF 전 연도 순서 고정.

## 2. 문제 제작 능력 — 실측

이번 소표본(3문항: 회계 mid·경영 easy·세법 hard, 생성/검토=codex, **교차검증=ollama 독립모델**):

- 구조 유효성 3/3, 검토 verdict: approve 2 · revise 1
- **정답키 1/3 오류 — 독립 교차검증이 포착**: 회계 CVP 문항이 해설로는 "6,000단위(=index 1)"를
  도출하고 키는 `correct_choice: 2`(7,200단위)로 기록. 원인은 해설의 한국식 "2번"(1-기반)을
  0-기반 인덱스로 그대로 적는 **인덱스 규약 혼동**. 수기 검산으로 확정(공헌이익 120,000원/묶음,
  목표공헌이익 2.4억 → 2,000묶음 → A 6,000단위).
- 세법 hard 문항은 수기 검산 결과 키 정확(손금불산입 138,000,000원 = 특례초과 1억 + 일반초과
  2천만 + 비지정 1.8천만). 플래그는 로컬모델 ANSWER 파싱 실패(-1)에 의한 절차적 오탐.

**구축한 가드**: `reconcile_correct_choice()` — 생성기에 `correct_answer`(정답 원문)를 요구하고
`choices[correct_choice]==correct_answer`를 코드로 대조. 불일치 시 교정(repaired), 대조 불가 시
폐기(dropped), 미제공 시 unverified 경고. 프롬프트 지시("0-기반")만으로는 막지 못함을 실측으로
확인했기 때문에 결정론 가드를 추가했다.

기존 실측(2026-06-05, 25문항): 구조 100%, 정답키 96%. + `--items` CLI로 약점 타겟 생성 가능해짐
(`subject:unit:difficulty:count`).

## 3. 합격 가이드라인 — 검증 결과 '구조적 단절' → 구축

검증에서 확인된 단절: 처방 엔진·진단·풀이맵 159·튜토리얼 23·용어그래프 1,001은 구현돼
있었으나 **처방의 `problems_to_solve`가 항상 빈 배열**(prescribe.py:301), 다주차 플랜 부재,
튜토리얼 API 부재, 선수개념 그래프 미사용, AI 풀이 미연결 — "따라가기만 하면"의 모든
관절이 끊겨 있었다.

구축(전부 결정론·근거 추적 evidence_refs 포함, 테스트 450개 통과):

| 모듈/엔드포인트 | 역할 |
|---|---|
| `engine/recommend.py` | 과락(<40%) 최우선·약개념 매칭·기시도 감점 점수로 problems_to_solve/skip 채움 |
| `engine/study_plan.py` | D-day→주차 분해, 단계 진행 압축, 과락 과목 시간 floor 15%, 망각 방지 유지시간 |
| `engine/learning_path.py` | 약개념→선수개념 BFS 역추적, 깊은 선수부터 학습 순서 + 자원(청크/문항/튜토리얼) |
| `GET /tutorials`, `/tutorials/{id}` | 23개 튜토리얼 노출 |
| `GET /practice`, `/practice/{id}` | 문항 뱅크 159 (정답·해설 비노출, 커서 페이지네이션) |
| `POST /attempts/diagnose` (확장) | 시도 후 공식 해설 반환 |
| `POST /practice/{id}/ai-explain` | 라우팅 solver AI 풀이 — 시도한 문항만(403), blind dict(정답 필드 제거 후 solve), 5/min 제한, 키 불일치 정직 표기 |
| `GET /learning-path` | 활성 처방의 약개념 → 학습 경로 |

학습 루프: 진단 → 처방(문항+로드맵) → 연습(무정답) → 시도 진단(해설+오답원인+다음행동)
→ 로그 누적 → `/user-state/refresh` 재진단 → 갱신된 처방. 전 단계 API로 닫힘.

### 3.1 적대적 리뷰 적발 → 수정 (정답 노출 경계)

이중 리뷰(내부 code-reviewer + codex 적대적)가 정답 노출 우회 3경로를 적발, 전부 수정:

1. **정적 마운트 우회 (P1)**: `prototype/problem_solution_maps.json`(정답 은행 전체)이
   정적 서빙으로 공개되고 있었음 — `_UiStaticFiles`로 해당 파일 404 차단.
2. **공개 evidence 우회 (P1)**: `/evidence/problem_solution_map/{id}`가 무인증으로
   정답키·해설 반환 — 정답 포함 evidence 2종을 인증+해당 문항 시도 후로 게이트.
3. **blind dict 중첩 누수 (P2)**: ai-explain의 solver 입력에서 top-level 정답 필드만
   제거하고 `solution_paths.answer_index`가 남아 있었음 — 블랙리스트를 화이트리스트
   (`_SOLVER_INPUT_FIELDS`)로 교체.
4. **중복 과목 음수 시간 (P2)**: 같은 과목을 중복 입력하면 과락 floor 중복 적용으로
   주간 배분에 음수 시간 발생 — API 422 거부 + 엔진 dedupe/클램프 이중 방어.

전부 회귀 테스트로 고정 (tests/test_guidance_api.py).

## 4. 남은 한계 (정직 기록)

### 해소됨 (2026-06-13~14)
1. ~~실제 기출 PDF 미수집~~ **해소** — 금융감독원 공식 2026 1차 기출 직접 수집·파싱·실측(§1.1).
2. ~~상법 실기출 검증 부재~~ **해소** — 실제 상법 40문항 97.5%(§1.1).
3. ~~경제 수식 문항 측정 불가~~ **해소** — 페이지 렌더+비전 전사로 68문항 복원·측정(§1.2).
4. ~~codex 타임아웃으로 미해결 5문항~~ **해소** — 900초 재측정으로 미해결 0(§1.1).

### 외부 자원이 필요해 현 세션에서 극복 불가 (정직 기록)
5. **로컬 단독 세법 과락권** — qwen3.5:27b의 다단계 계산 한계(모델 속성). 라우팅(세법→codex)으로
   운영상 해소했으나 로컬 모델 자체를 바꾸려면 더 큰/강한 로컬 모델 또는 파인튜닝 필요. **불가피**.
6. **codex 실시간 부적합** — 문항당 80~600초는 codex의 추론 깊이에서 오는 속성. 저지연이 필요한
   per-request ai-explain은 `AI_EXPLAIN_BACKEND=anthropic` 권장(코드 반영 완료). anthropic 실측은
   **API 키 필요** — 현 keyless 환경에서 측정 불가.
7. **decision rules 자동 추출(M4)** — 합격수기 텍스트 수집·LLM 추출 파이프라인. **합격수기 저작권
   검토**가 선결(현 35개는 수동 machine_draft). 권리 확보 전 진행 불가.
8. **추천 가중치 실로그 보정** — 현 휴리스틱(약점·빈도·기시도)을 A/B·수렴으로 보정하려면 **실사용
   학습 로그 누적**이 선결. 데이터 없이 합성 불가.
9. **수집 기출 RAG/학습 투입** — `train_after_rights_review` 정책. **공식 기출 학습 이용 권리 검토**
   전까지 eval 전용 유지(정책 준수).
10. **UI 미통합** — 프로토타입 UI가 새 엔드포인트(problems_to_solve·study_plan·/practice·
    /learning-path)를 아직 렌더링 안 함. 코드 작업으로 가능하나 별도 트랙(다음 마일스톤).

5~9는 외부 자원(API 키·저작권·실사용 데이터·더 강한 로컬 모델) 없이는 닫을 수 없다 —
"극복"이 아니라 "차단 사유 명시"가 정직한 처리다. 10은 가능하나 범위상 다음 작업.

## 5. 재현 명령

```bash
# 라우팅 제품 경로 E2E
CPA_OLLAMA_MODEL=qwen3.5:27b-int4 .venv/bin/python scripts/benchmark_routing.py \
  --routes tax:codex --default ollama --rag data/seeds/rag --per-subject 2

# 생성 품질(독립 교차검증)
CPA_OLLAMA_MODEL=qwen3.5:27b-int4 .venv/bin/python scripts/verify_gen_quality.py

# 실제 기출 수집 → 파싱 → 실측 (§1.1)
.venv/bin/python scripts/collect_real_exams.py        # 금융감독원 공식 PDF
.venv/bin/python scripts/parse_real_exams.py          # → parsed/<year>/<subject>.questions.json
CPA_CODEX_TIMEOUT=600 .venv/bin/python scripts/benchmark_routing.py \
  --questions-files data/real_exams/cpa1/parsed/2026/corporate_law.questions.json \
  --routes tax:codex --default codex --rag data/seeds/rag --per-subject 0 --skip-math-lossy

# 경제 수식 문항 비전 복원 (§1.2)
.venv/bin/python scripts/render_math_lossy_pages.py --subject economics   # 페이지 PNG 렌더
# → 비전 에이전트로 전사(워크플로) → /tmp/econ_vision*.json
.venv/bin/python scripts/apply_vision_recovery.py    # → parsed/<year>/economics.recovered.json
CPA_CODEX_TIMEOUT=600 .venv/bin/python scripts/benchmark_routing.py \
  --questions-files data/real_exams/cpa1/parsed/2026/economics.recovered.json \
  --default codex --rag data/seeds/rag --per-subject 0

# 전체 테스트 / 린트
.venv/bin/pytest -q && ruff check .
```

산출물: `data/runtime/benchmark_runs/real2026-codex-{clean,rerun17,corrected}.json` (런타임, git 미커밋).
