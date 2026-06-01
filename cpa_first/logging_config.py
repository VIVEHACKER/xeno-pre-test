"""구조화 JSON 로깅 (structlog + stdlib 통합).

- prod: stdout으로 JSON 1라인/이벤트 (PaaS 로그 파이프라인 친화)
- dev: 사람이 읽기 쉬운 콘솔 렌더링
- uvicorn/gunicorn 로거도 동일 포매터로 흘려보냄.
- request_id / user_id 같은 컨텍스트는 structlog.contextvars로 바인딩.
"""

from __future__ import annotations

import logging
import sys

import structlog

from cpa_first.config import Settings

_SHARED_PROCESSORS: list = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
]


def configure_logging(settings: Settings) -> None:
    """앱 부팅 시 1회 호출. stdlib + structlog을 한 파이프라인으로 묶는다."""
    level = getattr(logging, settings.log_level, logging.INFO)

    if settings.log_json:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED_PROCESSORS,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # uvicorn/gunicorn 로거가 자체 핸들러로 중복 출력하지 않도록 루트로 전파만.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "gunicorn.error", "gunicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True

    # SQLAlchemy 엔진 로그는 너무 시끄러우므로 WARNING 이상만.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
