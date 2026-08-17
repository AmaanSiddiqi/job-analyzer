"""Admin-gated trigger for board-JSON ingestion (P1).

Mirrors the /scrape route conventions: X-Admin-Key auth, per-IP rate limit,
503 with an explanatory message while the feature flag is off.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import require_admin_key
from ..database import get_db
from ..ingestion.discovery import probe_pending, render_yaml_suggestions
from ..ingestion.service import run_aggregator_ingestion, run_board_ingestion
from ..rate_limit import limiter
from ..settings import get_settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


class SourceCountsOut(BaseModel):
    fetched: int
    kept: int
    filtered_location: int
    duplicate_in_run: int
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


class AggregatorResponse(BaseModel):
    sources: dict[str, SourceCountsOut]
    new_company_suggestions: int


@router.post(
    "/aggregators", response_model=AggregatorResponse, dependencies=[Depends(require_admin_key)]
)
@limiter.limit("2/minute")
async def ingest_aggregators(
    request: Request, db: AsyncSession = Depends(get_db)
) -> AggregatorResponse:
    """Run one Adzuna+Jooble pass (also mines company suggestions)."""
    settings = get_settings()
    if not settings.enable_aggregator_ingestion:
        raise HTTPException(
            status_code=503,
            detail="Aggregator ingestion is disabled. Set ENABLE_AGGREGATOR_INGESTION=true.",
        )
    if not (settings.adzuna_app_id and settings.adzuna_app_key) and not settings.jooble_api_key:
        raise HTTPException(
            status_code=503,
            detail="No aggregator credentials configured (ADZUNA_APP_ID/ADZUNA_APP_KEY, JOOBLE_API_KEY).",
        )
    result = await run_aggregator_ingestion(db)
    suggestions = result.pop("new_company_suggestions")
    return AggregatorResponse(
        sources={s: SourceCountsOut(**vars(c)) for s, c in result.items()},  # type: ignore[arg-type]
        new_company_suggestions=int(suggestions),  # type: ignore[arg-type]
    )


class ProbeResponse(BaseModel):
    probed: int
    board_found: int
    no_ca_roles: int
    no_board: int


@router.post(
    "/suggestions/probe", response_model=ProbeResponse, dependencies=[Depends(require_admin_key)]
)
@limiter.limit("2/minute")
async def probe_suggestions(request: Request, db: AsyncSession = Depends(get_db)) -> ProbeResponse:
    """Probe pending company suggestions for public boards (network)."""
    return ProbeResponse(**await probe_pending(db))


@router.get(
    "/suggestions", response_class=PlainTextResponse, dependencies=[Depends(require_admin_key)]
)
@limiter.limit("10/minute")
async def list_suggestions(request: Request, db: AsyncSession = Depends(get_db)) -> str:
    """Ready-to-paste companies.yaml entries for every verified discovery."""
    yaml_block = await render_yaml_suggestions(db)
    return yaml_block or "# no board_found suggestions yet — run POST /ingest/suggestions/probe\n"
