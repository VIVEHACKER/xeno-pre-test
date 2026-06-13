"""LLM invoke 어댑터 — solver/validator/generator의 `invoke(system, user) -> str` 백엔드.

Anthropic 키 없이도 풀이/생성이 가능하도록 여러 백엔드를 제공한다.

백엔드:
- codex   : 로컬 codex CLI(`codex exec`, 헤드리스). Anthropic 키 불필요(codex 자체 인증 사용).
            한 호출당 수십 초·수만 토큰 → 배치/오프라인 벤치마크·생성용. 저지연 per-request 부적합.
- ollama  : 로컬 ollama HTTP(`/api/chat`). 완전 오프라인. 모델 품질은 로컬 모델에 의존.
- anthropic: Anthropic API(키 필요). 저지연 per-request 운영용.

선택: 인자 backend > 환경변수 CPA_LLM_BACKEND > 기본 codex.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

Invoke = Callable[[str, str], str]


class InvokeError(RuntimeError):
    """LLM 백엔드 호출 실패."""


# ───────────────────────── codex (codex exec, headless) ─────────────────────────


def codex_invoke(
    system: str,
    user: str,
    *,
    model: str | None = None,
    timeout: int = 240,
    codex_bin: str = "codex",
) -> str:
    """`codex exec`를 헤드리스로 호출하고 최종 메시지만 반환.

    system+user를 하나의 프롬프트로 합쳐 stdin으로 전달(긴 프롬프트 argv 한계 회피).
    `-o`로 최종 메시지를 파일에 받아 그대로 읽는다.
    """
    prompt = f"{system.strip()}\n\n---\n\n{user.strip()}\n"
    with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False) as tf:
        out_path = tf.name
    try:
        cmd = [
            codex_bin,
            "exec",
            "--skip-git-repo-check",
            "-s",
            "read-only",
            "--color",
            "never",
            "-o",
            out_path,
        ]
        if model:
            cmd += ["-m", model]
        cmd += ["-"]  # 프롬프트는 stdin으로
        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise InvokeError(f"codex CLI not found: {codex_bin}") from exc
        except subprocess.TimeoutExpired as exc:
            raise InvokeError(f"codex exec timed out after {timeout}s") from exc

        msg = Path(out_path).read_text(encoding="utf-8").strip()
        if not msg:
            msg = (proc.stdout or "").strip()
        if proc.returncode != 0 and not msg:
            raise InvokeError(
                f"codex exec failed (rc={proc.returncode}): {(proc.stderr or '')[-400:]}"
            )
        return msg
    finally:
        try:
            os.unlink(out_path)
        except OSError:
            pass


# ───────────────────────── ollama (local HTTP) ─────────────────────────


def ollama_invoke_factory(
    model: str = "qwen2.5:32b",
    *,
    host: str = "http://localhost:11434",
    timeout: int = 240,
    num_predict: int = 8000,
    num_ctx: int = 16000,
) -> Invoke:
    """로컬 ollama `/api/chat` 기반 invoke. 완전 오프라인.

    num_predict/num_ctx를 항상 명시한다 — ollama 기본 컨텍스트(4k)는 RAG 프롬프트
    + reasoning 모델의 긴 thinking을 담지 못해 ANSWER 줄이 잘린다(벤치마크 실측과
    제품 경로의 정확도 괴리 원인이었음).
    """

    def _invoke(system: str, user: str) -> str:
        import httpx

        try:
            resp = httpx.post(
                f"{host.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "stream": False,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "options": {
                        "temperature": 0.0,
                        "num_predict": num_predict,
                        "num_ctx": num_ctx,
                    },
                },
                timeout=timeout,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise InvokeError(f"ollama call failed: {exc}") from exc
        data = resp.json()
        return (data.get("message") or {}).get("content", "") or ""

    return _invoke


# ───────────────────────── anthropic (API key 필요) ─────────────────────────


def anthropic_invoke_factory(
    model: str = "claude-opus-4-7",
    *,
    max_tokens: int = 2000,
) -> Invoke:
    """Anthropic API 기반 invoke. ANTHROPIC_API_KEY 필요."""

    try:
        import anthropic
    except ImportError as exc:
        raise InvokeError("anthropic 백엔드는 `pip install anthropic` 필요") from exc
    client = anthropic.Anthropic()

    def _invoke(system: str, user: str) -> str:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "\n".join(parts)

    return _invoke


# ───────────────────────── 백엔드 선택 ─────────────────────────


def resolve_backend(backend: str | None = None) -> str:
    return (backend or os.environ.get("CPA_LLM_BACKEND") or "codex").strip().lower()


def make_invoke(backend: str | None = None, *, model: str | None = None) -> Invoke:
    """백엔드 이름으로 invoke 콜백 생성.

    model 우선순위: 인자 > CPA_LLM_MODEL > 백엔드 기본.
    """
    name = resolve_backend(backend)
    model = model or os.environ.get("CPA_LLM_MODEL") or None

    if name == "codex":
        # 세법 계산형·다단계 추론 문항은 240초를 넘길 수 있다(실측: 벤치마크 chose=-1의
        # 주원인이 codex 타임아웃이었음 — 재실행하니 정답). env로 조정 가능하게 한다.
        codex_timeout = int(os.environ.get("CPA_CODEX_TIMEOUT", "240"))
        return lambda system, user: codex_invoke(system, user, model=model, timeout=codex_timeout)
    if name == "ollama":
        return ollama_invoke_factory(
            model=model or os.environ.get("CPA_OLLAMA_MODEL", "qwen2.5:32b"),
            host=os.environ.get("CPA_OLLAMA_HOST", "http://localhost:11434"),
            timeout=int(os.environ.get("CPA_OLLAMA_TIMEOUT", "600")),
            num_predict=int(os.environ.get("CPA_OLLAMA_NUM_PREDICT", "8000")),
            num_ctx=int(os.environ.get("CPA_OLLAMA_NUM_CTX", "16000")),
        )
    if name == "anthropic":
        return anthropic_invoke_factory(model=model or "claude-opus-4-7")
    raise InvokeError(f"unknown LLM backend: {name} (codex|ollama|anthropic 중 하나)")
