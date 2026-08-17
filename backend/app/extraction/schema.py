"""JobComponents — the structured extraction contract (CLAUDE.md v1).

Sent to the API as a JSON schema via structured outputs, so the model cannot
return a shape that fails validation. Extend only with a stated reason; every
change needs a new prompt version and a re-run of the eval before any backfill.

Design rules that matter more than the field list:
  * Anything not stated in the posting is None, never a guess. Compensation
    and visa flags especially — a wrong "sponsors visas" is worse for the user
    than an honest "not stated".
  * Every visa flag that isn't None must be backed by verbatim evidence from
    the posting (enforced in code below, not just asked for in the prompt).
"""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Seniority(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"
    STAFF = "staff"
    LEAD = "lead"
    UNKNOWN = "unknown"


class RemotePolicy(StrEnum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    UNKNOWN = "unknown"


class CompPeriod(StrEnum):
    YEAR = "year"
    MONTH = "month"
    HOUR = "hour"


class Compensation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_amount: float | None = Field(
        None, description="Lower bound as stated. None if the posting gives no figure."
    )
    max_amount: float | None = Field(
        None, description="Upper bound as stated. None if the posting gives no figure."
    )
    currency: str | None = Field(
        None, description="ISO-4217 code, e.g. CAD, USD. None if not stated."
    )
    period: CompPeriod | None = Field(
        None, description="Whether the figures are per year, month, or hour."
    )
    is_estimated: bool = Field(
        False,
        description=(
            "True only when the posting itself labels the range as an estimate. "
            "Never infer a range the posting does not state."
        ),
    )

    @model_validator(mode="after")
    def _no_currency_without_amount(self) -> "Compensation":
        if (self.min_amount is not None or self.max_amount is not None) and not self.currency:
            # A bare number with no currency is unusable downstream (and
            # ambiguous between CAD and USD in Canadian postings).
            raise ValueError("compensation amounts require a currency")
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("compensation min_amount exceeds max_amount")
        return self


class VisaSignals(BaseModel):
    """The flagship feature. Tri-state by design: None means "the posting does
    not say", which is different from False ("the posting says no")."""

    model_config = ConfigDict(extra="forbid")

    sponsorship_available: bool | None = Field(
        None, description="Posting states the employer sponsors work visas."
    )
    requires_existing_authorization: bool | None = Field(
        None,
        description=(
            "Posting states applicants must already be authorized to work "
            "(e.g. 'must be legally entitled to work in Canada')."
        ),
    )
    citizenship_or_pr_required: bool | None = Field(
        None,
        description=(
            "Posting states citizenship or permanent residence is required "
            "(common for cleared / government work)."
        ),
    )
    evidence: list[str] = Field(
        default_factory=list,
        description=(
            "Verbatim phrases copied from the posting that justify the flags "
            "above. Required whenever any flag is not None. Copy exactly — do "
            "not paraphrase, and do not invent."
        ),
    )

    @property
    def any_flag_set(self) -> bool:
        return any(
            flag is not None
            for flag in (
                self.sponsorship_available,
                self.requires_existing_authorization,
                self.citizenship_or_pr_required,
            )
        )

    @model_validator(mode="after")
    def _flags_need_evidence(self) -> "VisaSignals":
        if self.any_flag_set and not [e for e in self.evidence if e.strip()]:
            raise ValueError("visa flags set without verbatim evidence")
        return self


class JobComponents(BaseModel):
    """Structured fields extracted from one job posting."""

    model_config = ConfigDict(extra="forbid")

    title_raw: str = Field(description="Job title exactly as posted.")
    title_normalized: str = Field(
        description="Title with company-specific decoration removed, e.g. "
        "'Senior Software Engineer, Platform (Remote)' -> 'Senior Software Engineer'."
    )
    seniority: Seniority = Field(
        Seniority.UNKNOWN, description="Seniority level implied by the title and requirements."
    )

    company_raw: str = Field(description="Employer name exactly as posted.")
    company_canonical: str = Field(
        description="Employer name with legal suffixes and punctuation normalized, "
        "e.g. 'Shopify Inc.' -> 'Shopify'."
    )

    skills: list[str] = Field(
        default_factory=list,
        description=(
            "Skills the posting asks for, using the provided canonical skill "
            "list. Use only ids from that list here."
        ),
    )
    skills_unmapped: list[str] = Field(
        default_factory=list,
        description=(
            "Skills the posting asks for that are NOT in the canonical list, "
            "as written. These feed a review queue — do not force them into "
            "a canonical id that does not fit."
        ),
    )

    required_quals: list[str] = Field(
        default_factory=list, description="Requirements the posting marks as required."
    )
    preferred_quals: list[str] = Field(
        default_factory=list, description="Requirements the posting marks as nice-to-have."
    )

    compensation: Compensation = Field(default_factory=Compensation)

    location_raw: str | None = Field(None, description="Location string as posted.")
    city: str | None = Field(None, description="City, if identifiable.")
    region: str | None = Field(
        None, description="Province/state name or code, if identifiable."
    )
    country: str | None = Field(
        None, description="ISO-3166 alpha-2 country code, e.g. CA, US. None if unclear."
    )
    remote_policy: RemotePolicy = Field(RemotePolicy.UNKNOWN)

    visa: VisaSignals = Field(default_factory=VisaSignals)

    posted_at: date | None = Field(
        None, description="Posting date if stated in the text. None otherwise."
    )
    language: str = Field(
        "en", description="ISO-639-1 code for the language the posting is written in."
    )
    extraction_confidence: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Your confidence that these fields reflect the posting: 0.9+ for a "
            "clear, complete posting; below 0.5 for truncated or garbled input."
        ),
    )
