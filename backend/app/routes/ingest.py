"""Admin-gated trigger for board-JSON ingestion (P1).

Mirrors the /scrape route conventions: X-Admin-Key auth, per-IP rate limit,
503 with an explanatory message while the feature flag is off.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin_key
from ..database import get_db
from ..ingestion.service import run_board_ingestion
from ..rate_limit import limiter
from ..settings import get_settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


class SourceCountsOut(BaseModel):
    fetched: int
    kept: int
    filtered_location: int
    new_raw: int
    new_postings: int
    failed_boards: list[str]


class IngestResponse(BaseModel):
    sources: dict[str, SourceCountsOut]


@router.post("/boards", response_model=IngestResponse, dependencies=[Depends(require_admin_key)])
@limiter.limit("2/minute")
async def ingest_boards(request: Request, db: AsyncSession = Depends(get_db)) -> IngestResponse:
    """Run one synchronous ingestion pass over every configured board."""
    if not get_settings().enable_board_ingestion:
        raise HTTPException(
            status_code=503,
            detail=(
                "Board ingestion is disabled. Set ENABLE_BOARD_INGESTION=true to enable "
                "(P1 supervised go-live step)."
            ),
        )
    counts = await run_board_ingestion(db)
    return IngestResponse(
        sources={board: SourceCountsOut(**vars(c)) for board, c in counts.items()}
    )
