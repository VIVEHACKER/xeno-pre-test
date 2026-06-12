"""--items 약점 타겟 spec 파싱(parse_items) 단위 테스트.

LLM 호출 없음 — 순수 파싱만 검증한다.
import 패턴은 tests/test_pipeline.py(`from scripts import ...`)를 따른다.

설계 명시 사항:
  - count 필드는 생략 가능하며 기본값 1 (약점 1건 찌르기가 기본 사용례)
  - 항목/필드 주변 공백 허용, 빈 항목(후행 쉼표)은 무시
  - subject는 cpa_first.subjects 등록 과목, difficulty는 easy|mid|hard
  - 위반 시 한국어 메시지의 ValueError (원본 항목 인용 → 근거 추적 가능)
"""

from __future__ import annotations

import pytest

from scripts import generate_eval_set as gen

# ── 정상 파싱 ────────────────────────────────────────────────────


def test_parse_items_basic():
    items = gen.parse_items("tax:corporate_tax:hard:2,accounting:cvp:mid:1")
    assert len(items) == 2
    assert items[0] == gen.GenItem("tax", "corporate_tax", "hard", 2)
    assert items[1] == gen.GenItem("accounting", "cvp", "mid", 1)


def test_parse_items_single_entry():
    (item,) = gen.parse_items("economics:micro_consumer:easy:3")
    assert item.subject == "economics"
    assert item.unit == "micro_consumer"
    assert item.difficulty == "easy"
    assert item.count == 3


def test_parse_items_whitespace_allowed():
    items = gen.parse_items(" tax : vat : mid : 2 ,  accounting:lease:hard:1 ")
    assert items[0] == gen.GenItem("tax", "vat", "mid", 2)
    assert items[1] == gen.GenItem("accounting", "lease", "hard", 1)


def test_parse_items_count_omitted_defaults_to_1():
    """설계: count 생략 허용, 기본 1."""
    (item,) = gen.parse_items("tax:vat:mid")
    assert item.count == 1


def test_parse_items_trailing_comma_ignored():
    items = gen.parse_items("tax:vat:mid:1,")
    assert len(items) == 1


def test_parse_items_count_is_int_type():
    (item,) = gen.parse_items("tax:vat:mid:7")
    assert isinstance(item.count, int)
    assert item.count == 7


def test_parse_items_preserves_order():
    items = gen.parse_items("corporate_law:company:easy,business:hr:mid,tax:vat:hard")
    assert [i.subject for i in items] == ["corporate_law", "business", "tax"]


# ── ValueError (한국어 메시지) ───────────────────────────────────


def test_parse_items_invalid_difficulty():
    with pytest.raises(ValueError, match="잘못된 난이도"):
        gen.parse_items("tax:vat:impossible:1")


def test_parse_items_unknown_subject():
    with pytest.raises(ValueError, match="미등록 과목"):
        gen.parse_items("history:wwii:easy:1")


def test_parse_items_too_few_fields():
    with pytest.raises(ValueError, match="잘못된 항목 형식"):
        gen.parse_items("tax:vat")


def test_parse_items_too_many_fields():
    with pytest.raises(ValueError, match="잘못된 항목 형식"):
        gen.parse_items("tax:vat:mid:1:extra")


def test_parse_items_empty_unit():
    with pytest.raises(ValueError, match="unit이 비어 있습니다"):
        gen.parse_items("tax::mid:1")


def test_parse_items_non_integer_count():
    with pytest.raises(ValueError, match="count는 정수여야 합니다"):
        gen.parse_items("tax:vat:mid:two")


def test_parse_items_zero_count():
    with pytest.raises(ValueError, match="count는 1 이상이어야 합니다"):
        gen.parse_items("tax:vat:mid:0")


def test_parse_items_negative_count():
    with pytest.raises(ValueError, match="count는 1 이상이어야 합니다"):
        gen.parse_items("tax:vat:mid:-2")


def test_parse_items_empty_spec():
    with pytest.raises(ValueError, match="비어 있습니다"):
        gen.parse_items("")


def test_parse_items_only_commas():
    with pytest.raises(ValueError, match="비어 있습니다"):
        gen.parse_items(" , , ")


def test_parse_items_error_quotes_offending_entry():
    """에러 메시지에 원본 항목이 그대로 인용돼 근거 추적이 가능해야 한다."""
    with pytest.raises(ValueError, match="tax:vat:ultra"):
        gen.parse_items("accounting:lease:mid:1,tax:vat:ultra:2")
