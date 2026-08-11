import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_raw = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/jobanalyzer")

# Railway (and many providers) emit postgres:// or postgresql:// — asyncpg needs the +asyncpg driver prefix
DATABASE_URL = (
    _raw.replace("postgres://", "postgresql+asyncpg://", 1)
    if _raw.startswith("postgres://")
    else _raw.replace("postgresql://", "postgresql+asyncpg://", 1)
    if _raw.startswith("postgresql://")
    else _raw
)

engine = create_async_engine(DATABASE_URL, echo=False)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
