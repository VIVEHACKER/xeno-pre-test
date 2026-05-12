"""Anthropic 호출을 invoke(system, user) -> str 인터페이스로 감싼다.

generator/validator에 그대로 주입 가능. ANTHROPIC_API_KEY 필요.
429/529/5xx에 대해 exponential backoff 재시도.
"""

from __future__ import annotations

import os
import random
import sys
import time
from typing import Callable


DEFAULT_MODEL = "claude-opus-4-7"
RETRYABLE_STATUS = {429, 500, 502, 503, 504, 529}


def make_anthropic_invoke(
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4000,
    max_retries: int = 6,
    base_delay: float = 4.0,
) -> Callable[[str, str], str]:
    """anthropic.Anthropic 클라이언트를 invoke 함수로 래핑.

    재시도 정책:
    - 429/529/5xx → exponential backoff (base_delay * 2^attempt + jitter, cap 90s)
    - 그 외 예외는 즉시 재발생
    """
    import anthropic  # type: ignore

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY 미설정. .env 파일 또는 환경변수에 키를 넣어주세요."
        )

    client = anthropic.Anthropic()

    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, anthropic.APIStatusError):
            return getattr(exc, "status_code", 0) in RETRYABLE_STATUS
        if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
            return True
        return False

    def invoke(system: str, user: str) -> str:
        for attempt in range(max_retries + 1):
            try:
                response = client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                parts: list[str] = []
                for block in response.content:
                    if getattr(block, "type", None) == "text":
                        parts.append(block.text)
                return "\n".join(parts)
            except Exception as exc:
                if attempt >= max_retries or not _is_retryable(exc):
                    raise
                delay = min(base_delay * (2 ** attempt) + random.uniform(0, 2), 90.0)
                print(
                    f"  [retry {attempt+1}/{max_retries}] {type(exc).__name__}: "
                    f"{str(exc)[:120]} — wait {delay:.1f}s",
                    flush=True,
                    file=sys.stderr,
                )
                time.sleep(delay)
        # 위 for 루프에서 반드시 return 또는 raise. 안전 가드:
        raise RuntimeError("invoke retries exhausted without resolution")

    return invoke
