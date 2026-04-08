from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
import os

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

AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session
