"""과목 레지스트리 (single source of truth).

엔진/스키마/UI/벤치마크가 모두 이 모듈을 참조한다. 새 과목을 추가하려면
SUBJECTS에 한 줄 추가하고 schemas/*.json의 enum을 SUBJECT_IDS와 동기화한다.

설계:
- Subject: 단일 과목 메타 (id, 한국어명, 1차/2차 단계, 매년 개정 여부)
- SUBJECTS: id → Subject 사전. 등록 순서 = UI/CLI 표시 순서
- GROUPS: 그룹 id → 멤버 frozenset. decision_rule.applicable_subjects 에서 사용
- matches_rule_subject(): general/group/single 매칭 통합 헬퍼
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Subject:
    id: str
    name_ko: str
    phases: tuple[str, ...]  # ("CPA_1",), ("CPA_1", "CPA_2"), ...
    requires_yearly_update: bool = False


# 등록 순서를 보존하기 위해 dict literal 사용 (Python 3.7+ 보장).
SUBJECTS: dict[str, Subject] = {
    "accounting": Subject("accounting", "회계", ("CPA_1", "CPA_2")),
    "tax": Subject("tax", "세법", ("CPA_1", "CPA_2"), requires_yearly_update=True),
    "business": Subject("business", "경영학", ("CPA_1",)),
    "economics": Subject("economics", "경제원론", ("CPA_1",)),
    "corporate_law": Subject("corporate_law", "기업법", ("CPA_1",)),
    "management": Subject("management", "경영", ("CPA_1",)),
    "finance": Subject("finance", "재무관리", ("CPA_1", "CPA_2")),
    "cost_accounting": Subject("cost_accounting", "원가관리", ("CPA_1", "CPA_2")),
}


# decision_rule.applicable_subjects 에서 쓰는 그룹.
# 그룹은 "이 멤버 모두를 user가 가져야" 매칭된다.
GROUPS: dict[str, frozenset[str]] = {
    "accounting_tax": frozenset({"accounting", "tax"}),
}


# rule/chunk/term 에서 "전체 과목 공통" 의미로 쓰는 와일드카드.
WILDCARD = "general"


def all_subject_ids() -> list[str]:
    """등록 순서대로 과목 id 목록."""
    return list(SUBJECTS)


def is_known_subject(subject: str) -> bool:
    return subject in SUBJECTS


def is_group(rule_subject: str) -> bool:
    return rule_subject in GROUPS


def group_members(group_id: str) -> frozenset[str]:
    return GROUPS[group_id]


def name_ko(subject: str) -> str:
    """알 수 없는 과목 id면 그대로 반환 (UI fallback 용)."""
    s = SUBJECTS.get(subject)
    return s.name_ko if s else subject


def schema_enum_subjects(*, include_wildcard: bool = False) -> list[str]:
    """JSON 스키마 enum용. 등록 순서 + 옵션으로 'general' 추가."""
    out = all_subject_ids()
    if include_wildcard:
        out.append(WILDCARD)
    return out


def schema_enum_rule_subjects() -> list[str]:
    """decision_rule.applicable_subjects 전용. 단일 과목 + 그룹 + general."""
    return all_subject_ids() + list(GROUPS) + [WILDCARD]


def matches_rule_subject(rule_subject: str, user_subjects: Iterable[str]) -> bool:
    """단일 과목/그룹/general 매칭을 한 번에 처리.

    - "general": 항상 True
    - 그룹 id (예: "accounting_tax"): 멤버 모두를 user가 가져야 True
    - 단일 과목 id: user가 그 과목을 가지면 True
    - 알 수 없는 값: False (스키마 검증으로 잡혀야 함)
    """
    user_set = set(user_subjects)
    if rule_subject == WILDCARD:
        return True
    if rule_subject in GROUPS:
        return GROUPS[rule_subject].issubset(user_set)
    if rule_subject in SUBJECTS:
        return rule_subject in user_set
    return False


def primary_subject(matched_rule_subjects: list[str], user_subjects: Iterable[str]) -> str:
    """rule.applicable_subjects 중 user에게 있는 것이 1개면 그것, 아니면 'mixed'.

    그룹 id는 'mixed'로 환원 (특정 단일 과목 task로 귀속할 수 없으므로).
    """
    user_set = set(user_subjects)
    matched_singles = [
        s for s in matched_rule_subjects
        if s in SUBJECTS and s in user_set
    ]
    if len(matched_singles) == 1:
        return matched_singles[0]
    return "mixed"
