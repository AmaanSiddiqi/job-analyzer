from datetime import datetime, timezone
from sqlalchemy import Text, DateTime, ARRAY, String, Integer
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


class JobPosting(Base):
    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    company: Mapped[str] = mapped_column(Text, nullable=False)
    location: Mapped[str] = mapped_column(Text, nullable=False)
    skills: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    date_scraped: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    source_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
