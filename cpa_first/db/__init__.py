"""DB 계층 — sync SQLAlchemy 2.0. 프로덕션 Postgres(psycopg), 테스트/dev SQLite.

이식 가능 타입(Uuid/JSON/String)만 사용 → 두 백엔드 호환.
KB(시드)는 여기 포함되지 않는다 — KB는 번들 읽기전용 메모리 로드.
"""

from cpa_first.db.base import Base
from cpa_first.db.session import Database, get_db

__all__ = ["Base", "Database", "get_db"]
