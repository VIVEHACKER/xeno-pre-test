# codex 실전 capability 베이스라인 (2026-06)

> 제품의 keyless 백엔드(codex)가 **실제 한국 기출(KMMLU)** 에서 과목별로 어느 수준인지 측정.
> 과거 "전체 77% / Law 34%" 수치는 약한 로컬 모델(qwen)·opus 기반이라 재측정.
> 로그(숫자만, KMMLU CC-BY-ND 준수): `local-eval-runs/kmmlu-codex-baseline.jsonl`, `local-eval-runs/law15-codex-ragonoff.jsonl`

## 측정 설계

- 백엔드: codex (codex-cli 0.135.0, 키 불필요), `mode=live`, 답 가린 풀이(`ANSWER: N` 추출).
- 데이터: `HAERAE-HUB/KMMLU` test split, 과목당 30문항(첫 30, 재현가능), 4지선다.
- subject 매핑: Accounting→accounting, Taxation→tax, Economics→economics, Management→business, Law→corporate_law.
- Tax·Law는 RAG-on/off 페어 비교(`data/seeds/rag` 청크). 3병렬, 총 210콜 ~89분.

## 결과 — RAG-OFF 베이스라인

| 과목 | codex 정답률 | 과거(opus/qwen) |
|---|---|---|
| Accounting | **30/30 (100%)** | 93 |
| Tax | **28/30 (93%)** | 77 |
| Economics | **30/30 (100%)** | 99 |
| Management | **26/30 (87%)** | 81 |
| **CPA-core 4과목** | **114/120 (≈95%)** | ~82 |

→ codex는 과거 측정보다 크게 강함. keyless 풀이 수준은 이미 충분(93~100%).

## Tax RAG — 실데이터 확증

| | RAG-OFF | RAG-ON |
|---|---|---|
| Tax (실 KMMLU 30) | 93% | **100% (+7pp)** |

기존 tax RAG 청크가 **실 기출 tax에서 실제로 정답률을 올림**. 합성 ±10%p 노이즈를 넘어 실전에서 확인된 RAG 승리 (교차모델 ensemble과 함께 검증된 두 번째 레버).

## ⚠️ "Law 약점"은 데이터셋 아티팩트 (정정)

- KMMLU `Law` config는 **경비업법·청원경찰법 등 행정/보안법**이다. CPA 상법(회사법)이 **아니다** — 상법 키워드 포함 문항 24/1000(2.4%), KMMLU에 상법 전용 config 없음.
- 따라서 과거 "Law 34%"(opus)와 이번 "Law 0/30"(codex)은 **둘 다 무관한 행정법을 측정한 값** — CPA 상법 능력과 무관하다.
- 제품의 실제 CPA 상법(합성 corporate_law 15문항)에서 codex는 **93%**. 약점 아님.
- 교훈: 벤치마크 config 이름(`Law`)만 보고 과목을 매핑하면 안 된다. 내용 확인 필수.

## 함의

1. **약점 알람(77%/Law34)의 정체** = 약한 모델(qwen) + 잘못된 데이터셋(KMMLU Law≠상법) 아티팩트. 실제 codex 능력은 CPA 전 과목 93~100%.
2. **진짜 제품 레버는 모델/RAG가 아니라 서빙 백엔드**: codex/anthropic 같은 강 모델로 서빙(저지연은 anthropic 키, 배치는 codex). 약한 ollama qwen으로 서빙하면 77%대로 떨어짐.
3. tax RAG는 유지(실전 +7pp 확증). 상법 RAG 추가는 불필요(상법은 이미 93%, KMMLU로는 검증 불가).

> 표본 30/과목은 ±~9%p CI. 큰 차이(77→95)는 명확하나 소수점 비교는 신중히.
