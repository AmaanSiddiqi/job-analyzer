from datetime import UTC, datetime

from sqlalchemy import ARRAY, DateTime, Index, Integer, String, Text, text
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
        default=lambda: datetime.now(UTC),
    )
    source_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        # GET /jobs's default listing orders by this with no filter — a full
        # table scan + sort on every unfiltered page load without it (AUDIT.md §4)
        Index("ix_job_postings_date_scraped", text("date_scraped DESC")),
        # trends.py GROUP BY company / ORDER BY count
        Index("ix_job_postings_company", "company"),
        # jobs.py filters func.lower(company) == ... exactly — a plain index on
        # `company` doesn't serve a lower() comparison, this is the matching
        # expression index
        Index("ix_job_postings_company_lower", text("lower(company)")),
        # trends.py GROUP BY title
        Index("ix_job_postings_title", "title"),
        # unnest(skills) queries across /trends/skills, /trends/skills/history
        Index("ix_job_postings_skills_gin", "skills", postgresql_using="gin"),
    )
