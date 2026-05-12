"""Phase 2 부트스트랩: 15개 핵심 용어를 data/seeds/terms/*.term.json 으로 생성.

설계 문서: docs/specs/2026-05-12-term-knowledge-graph-design.md §10 Phase 2
실행 후 이 스크립트는 삭제해도 됨 (산출물이 source of truth).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "seeds" / "terms"

TERMS: list[dict] = [
    # ── accounting (5) ──────────────────────────────────────────
    {
        "term_id": "amortized-cost",
        "name_ko": "상각후원가",
        "name_en": "amortized cost",
        "aliases": ["상각원가", "AC"],
        "subject": "accounting",
        "unit": "financial_assets",
        "definition": "금융자산의 측정 기준 중 하나로, 취득원가에서 유효이자율법으로 상각한 후의 장부금액. 만기 시 액면금액과 일치한다. 회수 목적 보유 + SPPI 조건 충족 시 적용한다.",
        "formula": "기말 장부금액 = 기초 장부금액 + 유효이자수익 - 액면이자 수취액",
        "difficulty": "intermediate",
        "confusable_with": [
            {"term_id": "fair-value", "reason": "측정 기준이 달라 평가손익 인식 위치(당기손익 vs 기타포괄손익)가 갈린다"}
        ],
        "prerequisite_terms": ["effective-interest-rate"],
        "example": "액면 100만, 표면이자 5%, 유효이자율 6%, 만기 3년 사채를 상각후원가로 측정",
        "rights_status": "self_generated",
        "review_status": "ai_draft",
    },
    {
        "term_id": "effective-interest-rate",
        "name_ko": "유효이자율",
        "name_en": "effective interest rate",
        "aliases": ["유효이자율법", "EIR"],
        "subject": "accounting",
        "unit": "financial_assets",
        "definition": "금융상품의 미래 현금흐름 추정치를 최초 인식 시점 장부금액과 일치시키는 할인율. 이자수익/이자비용 인식의 기준이 되며 액면이자율과 다를 수 있다.",
        "formula": "이자수익 = 기초 장부금액 × 유효이자율",
        "difficulty": "intermediate",
        "confusable_with": [
            {"term_id": "nominal-interest-rate", "reason": "액면이자율은 현금 수취 기준, 유효이자율은 회수원가 기준이라 이자수익 크기가 달라진다"}
        ],
        "prerequisite_terms": [],
        "example": "액면이자율 5%로 발행된 사채를 시장이 할인 평가해 발행가가 떨어지면 유효이자율은 5%보다 높아진다",
        "rights_status": "self_generated",
        "review_status": "ai_draft",
    },
    {
        "term_id": "expected-credit-loss",
        "name_ko": "기대신용손실",
        "name_en": "expected credit loss",
        "aliases": ["ECL", "기대손실"],
        "subject": "accounting",
        "unit": "financial_assets",
        "definition": "K-IFRS 1109호 손상 모형. 신용 손실 발생 가능성을 확률 가중해 측정한다. Stage 1(12개월 ECL), Stage 2/3(전체 잔여기간 ECL)로 구분하고 신용위험의 유의적 증가로 단계 전이가 일어난다.",
        "formula": None,
        "difficulty": "advanced",
        "confusable_with": [
            {"term_id": "incurred-loss", "reason": "발생손실 모형은 사건 발생 후 인식, ECL은 사건 발생 전 기대치를 선반영한다"}
        ],
        "prerequisite_terms": ["amortized-cost"],
        "example": "정상 자산은 12개월 ECL을 인식하다가 신용위험이 유의적으로 증가하면 Stage 2로 전이되어 전체 잔여기간 ECL을 인식",
        "rights_status": "official_paraphrase",
        "review_status": "ai_draft",
    },
    {
        "term_id": "deferred-tax",
        "name_ko": "이연법인세",
        "name_en": "deferred tax",
        "aliases": ["이연법인세자산", "이연법인세부채", "DTA", "DTL"],
        "subject": "accounting",
        "unit": "income_tax_accounting",
        "definition": "회계상 장부금액과 세무상 자산/부채 가액의 일시적 차이에서 발생하는 미래 세효과. 가산 일시적 차이는 이연법인세부채, 차감 일시적 차이는 이연법인세자산을 발생시킨다.",
        "formula": "이연법인세 = 일시적 차이 × 미래 실현 시점의 평균 세율",
        "difficulty": "advanced",
        "confusable_with": [
            {"term_id": "current-tax", "reason": "당기법인세는 당기 과세소득 기준, 이연법인세는 미래 차이 해소 시점 기준이라 인식 시점과 금액 산정이 다르다"}
        ],
        "prerequisite_terms": [],
        "example": "감가상각 차이로 회계상 잔액이 세무상보다 작으면 차감 일시적 차이가 발생해 이연법인세자산이 인식된다",
        "rights_status": "self_generated",
        "review_status": "ai_draft",
    },
    {
        "term_id": "provision",
        "name_ko": "충당부채",
        "name_en": "provision",
        "aliases": ["충당금"],
        "subject": "accounting",
        "unit": "provisions",
        "definition": "지출 시기 또는 금액이 불확실한 부채. 현재의무 존재 + 자원 유출 가능성 높음 + 신뢰성 있는 추정 가능, 세 요건을 모두 충족할 때 인식한다. 하나라도 빠지면 우발부채로 주석 공시한다.",
        "formula": None,
        "difficulty": "intermediate",
        "confusable_with": [
            {"term_id": "contingent-liability", "reason": "충당부채는 인식 요건 충족 시 재무상태표에 부채 계상, 우발부채는 주석 공시만 한다"}
        ],
        "prerequisite_terms": [],
        "example": "제품 보증으로 인한 미래 수리 비용이 과거 실적상 신뢰성 있게 추정되면 충당부채로 인식한다",
        "rights_status": "official_paraphrase",
        "review_status": "ai_draft",
    },
    # ── tax (4) ─────────────────────────────────────────────────
    {
        "term_id": "comprehensive-taxation",
        "name_ko": "종합과세",
        "name_en": "comprehensive taxation",
        "aliases": ["종합소득과세"],
        "subject": "tax",
        "unit": "income_tax",
        "definition": "이자/배당/사업/근로/연금/기타 소득을 합산해 누진세율로 과세하는 방식. 금융소득 종합과세 기준금액(2천만원) 초과분이 대표적이다.",
        "formula": None,
        "difficulty": "intermediate",
        "confusable_with": [
            {"term_id": "separate-taxation", "reason": "분리과세는 다른 소득과 합산 없이 원천징수 세율로 종결, 종합과세는 합산해 누진율 적용"}
        ],
        "prerequisite_terms": [],
        "example": "금융소득이 연 2천만원을 초과하면 초과분이 다른 종합소득과 합산되어 누진세율로 과세된다",
        "rights_status": "self_generated",
        "review_status": "ai_draft",
    },
    {
        "term_id": "separate-taxation",
        "name_ko": "분리과세",
        "name_en": "separate taxation",
        "aliases": ["분리과세소득"],
        "subject": "tax",
        "unit": "income_tax",
        "definition": "특정 소득을 다른 소득과 합산하지 않고 원천징수 세율로 과세를 종결하는 방식. 신고/합산 의무가 없다.",
        "formula": None,
        "difficulty": "intermediate",
        "confusable_with": [
            {"term_id": "comprehensive-taxation", "reason": "종합과세는 합산 후 누진율, 분리과세는 원천징수 세율로 종결되어 신고 의무 자체가 다르다"}
        ],
        "prerequisite_terms": [],
        "example": "복권 당첨금은 일정 금액 이하는 분리과세로 원천징수만으로 과세가 끝난다",
        "rights_status": "self_generated",
        "review_status": "ai_draft",
    },
    {
        "term_id": "necessary-expense",
        "name_ko": "필요경비",
        "name_en": "necessary expense",
        "aliases": [],
        "subject": "tax",
        "unit": "income_tax",
        "definition": "소득세법상 사업/기타 소득의 총수입금액에서 차감하는 비용. 해당 소득을 얻기 위해 직접 지출했거나 통상 발생하는 비용으로 한정된다.",
        "formula": "사업소득금액 = 총수입금액 - 필요경비",
        "difficulty": "foundational",
        "confusable_with": [
            {"term_id": "deductible-expense", "reason": "필요경비는 소득세법 용어(개인사업자), 손금은 법인세법 용어로 인정 범위와 한도가 다르다"}
        ],
        "prerequisite_terms": [],
        "example": "프리랜서가 업무용 노트북을 구입했다면 사업과 직접 관련된 부분이 필요경비로 차감된다",
        "rights_status": "self_generated",
        "review_status": "ai_draft",
    },
    {
        "term_id": "deemed-input-vat",
        "name_ko": "의제매입세액",
        "name_en": "deemed input VAT",
        "aliases": ["의제매입세액공제"],
        "subject": "tax",
        "unit": "vat",
        "definition": "부가가치세 면세 농수산물 등을 구입해 과세재화의 원재료로 사용한 경우, 실제 부담하지 않은 매입세액을 일정 의제율로 인정해 매출세액에서 공제하는 제도.",
        "formula": "의제매입세액 = 면세 농수산물 매입가액 × 업종별 의제율",
        "difficulty": "advanced",
        "confusable_with": [
            {"term_id": "input-vat", "reason": "일반 매입세액은 실제 부담분, 의제매입세액은 실제 부담 없는 면세 매입을 의제로 인정한 것"}
        ],
        "prerequisite_terms": [],
        "example": "음식점업이 면세 농산물을 매입해 음식으로 판매하면 매입가의 일정 비율을 매출세액에서 공제 가능",
        "rights_status": "official_paraphrase",
        "review_status": "ai_draft",
    },
    # ── accounting/cost_management (3) ──────────────────────────
    {
        "term_id": "standard-cost",
        "name_ko": "표준원가",
        "name_en": "standard cost",
        "aliases": ["표준원가계산"],
        "subject": "accounting",
        "unit": "cost_management",
        "definition": "사전에 정한 단위당 표준 가격과 표준 수량을 기준으로 원가를 계산하는 방식. 실제원가와의 차이는 가격차이/수량차이/효율차이 등으로 분해해 통제 정보로 활용한다.",
        "formula": "표준원가 = 표준 수량 × 표준 가격",
        "difficulty": "intermediate",
        "confusable_with": [
            {"term_id": "actual-cost", "reason": "실제원가는 사후 측정, 표준원가는 사전 설정이라 차이 분석의 출발점이 된다"}
        ],
        "prerequisite_terms": [],
        "example": "직접재료비 표준이 단위당 2kg × 5,000원인데 실제 2.2kg × 4,800원으로 발생하면 수량차이와 가격차이로 분해",
        "rights_status": "self_generated",
        "review_status": "ai_draft",
    },
    {
        "term_id": "joint-cost",
        "name_ko": "결합원가",
        "name_en": "joint cost",
        "aliases": ["연산품원가"],
        "subject": "accounting",
        "unit": "cost_management",
        "definition": "하나의 공정에서 동시에 둘 이상의 연산품이 생산될 때, 분리점 이전까지 공통으로 발생한 원가. 분리점 이후 발생하는 추가가공원가(분리원가)와 구분된다.",
        "formula": None,
        "difficulty": "advanced",
        "confusable_with": [
            {"term_id": "separable-cost", "reason": "결합원가는 분리점 이전 공통 발생분, 분리원가는 분리점 이후 제품별 추적 가능분"}
        ],
        "prerequisite_terms": [],
        "example": "원유 정제에서 휘발유와 경유가 동시에 나올 때 분리점 진입 전까지의 원가가 결합원가",
        "rights_status": "self_generated",
        "review_status": "ai_draft",
    },
    {
        "term_id": "activity-based-cost",
        "name_ko": "활동기준원가",
        "name_en": "activity-based costing",
        "aliases": ["ABC", "활동기준원가계산"],
        "subject": "accounting",
        "unit": "cost_management",
        "definition": "제조간접원가를 활동 단위로 묶고, 각 활동의 원가동인(cost driver)에 따라 제품에 배부하는 원가계산 방식. 전통적 조업도 기준 배부의 왜곡을 줄인다.",
        "formula": "제품 배부 = Σ (활동별 원가 ÷ 활동별 원가동인 총량) × 제품의 원가동인 소비량",
        "difficulty": "advanced",
        "confusable_with": [
            {"term_id": "standard-cost", "reason": "표준원가는 예정 원가의 기준값, ABC는 간접원가 배부 방법론이라 분석 층위가 다르다"}
        ],
        "prerequisite_terms": [],
        "example": "기계가동시간이 아닌 '주문 처리 횟수'를 동인으로 사용해 소량다품종 제품의 원가를 더 정확히 배부",
        "rights_status": "self_generated",
        "review_status": "ai_draft",
    },
    # ── business/financial_management (3) ────────────────────────
    {
        "term_id": "wacc",
        "name_ko": "가중평균자본비용",
        "name_en": "weighted average cost of capital",
        "aliases": ["WACC", "가중평균자본비"],
        "subject": "business",
        "unit": "financial_management",
        "definition": "타인자본과 자기자본의 비용을 시장가치 기준으로 가중평균한 기업 전체의 자본비용. 법인세 절감 효과를 반영해 타인자본은 세후 이자비용을 사용한다.",
        "formula": "WACC = (E/V) × Re + (D/V) × Rd × (1 - t)",
        "difficulty": "intermediate",
        "confusable_with": [
            {"term_id": "cost-of-equity", "reason": "자기자본비용은 주주 요구수익률(Re), WACC는 부채비용까지 가중평균한 전체 자본비용"}
        ],
        "prerequisite_terms": [],
        "example": "자기자본 60%(Re 10%), 타인자본 40%(Rd 5%, 세율 25%) 기업의 WACC = 0.6×10% + 0.4×5%×0.75 = 7.5%",
        "rights_status": "self_generated",
        "review_status": "ai_draft",
    },
    {
        "term_id": "mm-proposition",
        "name_ko": "MM 명제",
        "name_en": "Modigliani-Miller proposition",
        "aliases": ["MM 정리", "MM 이론"],
        "subject": "business",
        "unit": "financial_management",
        "definition": "Modigliani-Miller의 자본구조 무관련 명제. 완전자본시장 가정 하에 기업가치는 자본구조와 무관하다(명제 I). 명제 II는 자기자본비용이 부채비율에 따라 선형으로 증가함을 보인다.",
        "formula": "명제 II: Re = Ra + (D/E) × (Ra - Rd)",
        "difficulty": "advanced",
        "confusable_with": [
            {"term_id": "trade-off-theory", "reason": "MM은 세금/파산비용 무시 가정, 상충이론은 절세효과와 파산비용의 trade-off로 최적 부채비율 존재"}
        ],
        "prerequisite_terms": ["wacc"],
        "example": "법인세가 도입된 MM 명제에서는 부채 사용이 기업가치를 증가시킨다 (이자비용 절세효과 = D × t)",
        "rights_status": "self_generated",
        "review_status": "ai_draft",
    },
    {
        "term_id": "option-delta",
        "name_ko": "옵션 델타",
        "name_en": "option delta",
        "aliases": ["델타"],
        "subject": "business",
        "unit": "financial_management",
        "definition": "기초자산 가격 1단위 변화에 대한 옵션 가격의 변화량. 콜옵션은 0~1, 풋옵션은 -1~0의 값을 가진다. 헤지비율로 사용된다.",
        "formula": "델타 = 옵션가격 변화 / 기초자산가격 변화",
        "difficulty": "advanced",
        "confusable_with": [
            {"term_id": "option-gamma", "reason": "델타는 기초자산 가격 변화에 대한 1차 민감도, 감마는 델타 자체의 변화율(2차 민감도)"}
        ],
        "prerequisite_terms": [],
        "example": "콜옵션 델타가 0.6이면 기초자산이 100원 오를 때 옵션가격은 60원 오른다. 헤지에는 콜 매도 1단위당 기초자산 0.6단위 매수",
        "rights_status": "self_generated",
        "review_status": "ai_draft",
    },
]


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for term in TERMS:
        path = OUT_DIR / f"{term['term_id']}.term.json"
        with path.open("w", encoding="utf-8", newline="\n") as f:
            json.dump(term, f, ensure_ascii=False, indent=2)
            f.write("\n")
        written += 1
    print(f"wrote {written} term files to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
