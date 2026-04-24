"""
Shared fixtures for API tests.

Uses FastAPI's dependency override to inject an async mock DB session so tests
run without a live PostgreSQL connection.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import AsyncMock, MagicMock

from app.main import app
from app.database import get_db


class _MockResult:
    """Minimal stand-in for SQLAlchemy's CursorResult / ScalarResult."""

    def __init__(self, rows=None, scalar=0):
        self._rows = rows or []
        self._scalar = scalar

    def all(self):
        return self._rows

    def scalar_one(self):
        return self._scalar

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self._rows)


def _make_db_session(scalar_value=0, rows=None):
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_MockResult(rows=rows, scalar=scalar_value))
    session.scalar = AsyncMock(return_value=scalar_value)
    return session


@pytest.fixture
def mock_db():
    return _make_db_session()


@pytest.fixture
async def client(mock_db):
    app.dependency_overrides[get_db] = lambda: mock_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
