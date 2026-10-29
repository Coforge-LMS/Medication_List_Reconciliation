"""Shared fixtures. DB tests use a real Postgres whose name ends in _test (TECHNICAL_PLAN §11)."""

import os

import pytest
from sqlalchemy import create_engine, text

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL  # must happen before app/db modules are imported


@pytest.fixture(scope="session")
def engine():
    if not TEST_DATABASE_URL:
        if os.environ.get("CI"):
            pytest.fail("TEST_DATABASE_URL must be set in CI")
        pytest.skip("TEST_DATABASE_URL not set (see README: createdb medrec_test)")
    assert TEST_DATABASE_URL.rsplit("/", 1)[-1].endswith("_test"), "refusing a non-test database"
    from db.models import Base  # lands in B5

    eng = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine):
    """Empty every table before the test; tests then observe real COMMIT/ROLLBACK."""
    from db.models import Base

    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    return engine
