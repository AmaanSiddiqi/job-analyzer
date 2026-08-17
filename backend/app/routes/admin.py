"""Admin views over the pipeline's review queues.

Plain JSON/text, admin-key gated — per CLAUDE.md the admin surface stays
minimal. /admin/deadletters arrives with the extraction pipeline.
"""

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin_key
from ..database import get_db
from ..models import UnmappedSkill
from ..rate_limit import limiter

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])


class UnmappedSkillOut(BaseModel):
    skill: str
    occurrences: int
    first_seen: str
    last_seen: str
    status: str


class UnmappedSkillsResponse(BaseModel):
    total: int
    skills: list[UnmappedSkillOut]


@router.get("/unmapped-skills", response_model=UnmappedSkillsResponse)
@limiter.limit("30/minute")
async def list_unmapped_skills(
    request: Request,
    status: str = Query("pending", description="pending | mapped | rejected"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> UnmappedSkillsResponse:
    """Skills the extractor produced that the taxonomy doesn't cover.

    Ordered by occurrences so the weekly review starts with the entries that
    would buy the most coverage.
    """
    rows = (
        (
            await db.execute(
                select(UnmappedSkill)
                .where(UnmappedSkill.status == status)
                .order_by(UnmappedSkill.occurrences.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return UnmappedSkillsResponse(
        total=len(rows),
        skills=[
            UnmappedSkillOut(
                skill=r.skill,
                occurrences=r.occurrences,
                first_seen=r.first_seen.isoformat(),
                last_seen=r.last_seen.isoformat(),
                status=r.status,
            )
            for r in rows
        ],
    )
