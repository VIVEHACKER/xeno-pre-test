"""Alembic 환경. DATABASE_URL은 cpa_first.config에서 읽고, target_metadata는
cpa_first.db의 모든 모델 메타데이터를 사용한다 (autogenerate 지원).
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from cpa_first.config import get_settings

# 모든 모델을 메타데이터에 등록.
from cpa_first.db import models  # noqa: F401,E402  (side-effect import)
from cpa_first.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_settings = get_settings()
# alembic.ini에 url을 두지 않고 설정에서 주입.
config.set_main_option("sqlalchemy.url", _settings.database_url)


def _render_as_batch() -> bool:
    # SQLite는 ALTER 제약이 많아 batch 모드 필요 (dev/test 마이그레이션 호환).
    return _settings.database_url.startswith("sqlite")


def run_migrations_offline() -> None:
    context.configure(
        url=_settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_render_as_batch(),
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_render_as_batch(),
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
