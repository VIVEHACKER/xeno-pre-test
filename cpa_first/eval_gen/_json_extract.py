"""LLM 출력에서 JSON 객체를 추출.

모델은 ```json 코드블록 또는 일반 텍스트 안에 JSON을 섞어 반환할 수 있다.
첫 번째 균형 잡힌 { ... } 짝을 시도한 뒤 실패하면 None을 반환.
"""

from __future__ import annotations

import json
import re
from typing import Any


_CODE_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def extract_json_object(raw: str) -> Any | None:
    """첫 번째로 파싱 가능한 JSON 객체를 반환. 실패 시 None."""
    if not raw or not isinstance(raw, str):
        return None

    # 1) ```json ... ``` 코드블록
    m = _CODE_BLOCK.search(raw)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 2) 첫 '{'부터 마지막 '}'까지 통째로 시도
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass

    # 3) 전체 raw를 그대로 시도
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None
