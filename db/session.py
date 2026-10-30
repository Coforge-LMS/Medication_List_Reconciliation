"""Lazy engine from DATABASE_URL and the per-request session dependency (TECHNICAL_PLAN §5)."""

import os
from collections.abc import Iterator
from functools import cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session


@cache
def get_engine() -> Engine:
    """Build the engine on first use, so importing the app never needs a database."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set (e.g. postgresql+psycopg://user:pw@host/db)")
    return create_engine(url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    with Session(get_engine()) as session:
        yield session
