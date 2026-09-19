"""JobComponents — the structured extraction contract (CLAUDE.md v1).

Sent to the API as a JSON schema via structured outputs, so the model cannot
return a shape that fails validation. Extend only with a stated reason; every
change needs a new prompt version and a re-run of the eval before any backfill.

Design rules that matter more than the field list:
  * Anything not stated in the posting is None, never a guess. Compensation and
    eligibility especially — a wrong "5+ years required" wrongly excludes a user
    from a role they could have got, which is the failure that costs them most.
  * Claims that drive ranking (the experience requirement, any visa flag) must
    be backed by verbatim evidence from the posting — enforced by the validators
    below, not merely requested in the prompt.

**The shape here is dictated by two hard, measured API limits.** Both were found
by bisecting against the real API, not from docs:

  1. **Field order decides whether the schema compiles at all.** The same
     fourteen fields compile when the four nested models are declared first and
     are rejected with `400 "Schema is too complex."` when they come last or sit
     interleaved among the scalars — at a byte-identical 3,472-char schema
     either way. Size is therefore not the constraint people assume it is: a
     3,472-char schema compiles while a 3,459-char one with the same fields in a
     worse order does not. Two related limits, also measured: unions are
     expensive (20 *required* fields compile, but 12 *optional* ones — `X | None`,
     which renders as `anyOf` — fail with `400 "Grammar compilation timed out."`,
     ceiling ~11 across the whole schema), and folding related scalars into a
     nested model buys top-level width, which is why city/region/country live in
     `Location`.
  2. Long `description=` text and class docstrings are serialized into the
     schema too, so per-field semantics live in `prompts.py` instead — where
     they cost (cached) prompt tokens rather than schema budget. This is not a
     style preference: descriptions and docstrings alone were 449 chars here,
     and with them the schema was rejected while the identical field shape
     without them compiled. Anything explanatory in this file must be a `#`
     comment, never a docstring or a `description=`.

So tri-state fields use the `Stated` enum rather than `bool | None`: a required
enum costs no union, reads more clearly to the model ("not_stated" beats null),
and carries the same three-way meaning. Optional strings use `""` and optional
amounts use `0`, converted back to real NULLs at the service boundary — the
database columns stay properly nullable. Only `min_years_experience` keeps a
real union, because it is the field the product ranks on and null-vs-zero is a
distinction worth spending the budget to keep explicit.

**Four fields the model used to return are gone**: `title_raw`, `company_raw`,
`location_raw` and `posted_at`. Each duplicated a column `raw_listings` already
holds straight from the board API, so asking for them spent schema budget and
output tokens to produce a *less* reliable copy — a model paraphrases a title,
the API does not. `_to_row` fills those columns from the raw row instead.

Comments like this one are free: they never reach the wire.
"""

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
    UNKNOWN = "unknown"


# Three-way answer for "does the posting say X?" — replaces `bool | None`.
# NOT_STATED is the common case and the safe default: it means the posting does
# not address the question, which is different from NO (it addresses it and the
# answer is negative). A docstring here would be serialized into the schema as a
# `description`; a comment is free.
class Stated(StrEnum):
    YES = "yes"
    NO = "no"
    NOT_STATED = "not_stated"

    def to_bool(self) -> bool | None:
        """None for NOT_STATED, so the DB keeps a true NULL."""
        return {Stated.YES: True, Stated.NO: False}.get(self)


class Compensation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 0 means "the posting states no figure" — a $0 salary is meaningless, so
    # the sentinel is unambiguous and costs no union budget.
    min_amount: float = 0.0
    max_amount: float = 0.0
    currency: str = ""
    period: CompPeriod = CompPeriod.UNKNOWN
    is_estimated: bool = False

    @property
    def has_amount(self) -> bool:
        return self.min_amount > 0 or self.max_amount > 0

    @model_validator(mode="after")
    def _sane_amounts(self) -> "Compensation":
        if self.has_amount and not self.currency:
            # A bare number is ambiguous between CAD and USD in Canadian
            # postings, and unusable downstream.
            raise ValueError("compensation amounts require a currency")
        if self.min_amount > 0 and self.max_amount > 0 and self.min_amount > self.max_amount:
            raise ValueError("compensation min_amount exceeds max_amount")
        return self


# Tri-state throughout: None = the posting doesn't say, which is different from
# False = the posting says no. Demoted from flagship on measured evidence (these
# fire on under 1% of Canadian postings — see CLAUDE.md) but kept, because the
# cases where citizenship or clearance genuinely gates a role are real and three
# nullable booleans cost nothing to carry.
class VisaSignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sponsorship_available: Stated = Stated.NOT_STATED
    requires_existing_authorization: Stated = Stated.NOT_STATED
    citizenship_or_pr_required: Stated = Stated.NOT_STATED
    evidence: list[str] = Field(default_factory=list)

    @property
    def any_flag_set(self) -> bool:
        return any(
            flag is not Stated.NOT_STATED
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


# The flagship signal family: experience requirements appear in 27.9% of real
# postings and only 17% of those are open to <=2 years, versus under 1% for visa
# signals (CLAUDE.md product thesis).
class EligibilitySignals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The single union we spend budget on: null and 0 mean different things here
    # ("unstated" vs "no experience required") and both are useful to the feed.
    min_years_experience: int | None = Field(None, ge=0, le=40)
    degree_required: Stated = Stated.NOT_STATED
    french_required: Stated = Stated.NOT_STATED
    is_new_grad_friendly: Stated = Stated.NOT_STATED
    is_internship_or_coop: Stated = Stated.NOT_STATED
    evidence: list[str] = Field(default_factory=list)

    @property
    def any_gate_set(self) -> bool:
        return self.min_years_experience is not None or any(
            v is not Stated.NOT_STATED
            for v in (
                self.degree_required,
                self.french_required,
                self.is_new_grad_friendly,
                self.is_internship_or_coop,
            )
        )

    @model_validator(mode="after")
    def _experience_claim_needs_evidence(self) -> "EligibilitySignals":
        # Only the experience number is evidence-gated: it is what the feed ranks
        # on, and a fabricated "5+ years" would wrongly exclude a user from a
        # role they could get. The booleans are lower-stakes, and demanding a
        # quote for each would push the model to invent them.
        if self.min_years_experience is not None and not [
            e for e in self.evidence if e.strip()
        ]:
            raise ValueError("min_years_experience set without verbatim evidence")
        return self


# Nested purely to buy schema budget — see the module docstring. Empty string =
# the posting doesn't say; converted to NULL at the service boundary so the
# columns stay honestly nullable.
class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    city: str = ""
    region: str = ""
    country: str = ""


class JobComponents(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # ---- Nested models first. This ordering is load-bearing, not cosmetic ----
    # The exact same fourteen fields compile when the four nested models lead and
    # fail with `400 "Schema is too complex."` when they trail or are interleaved
    # among the scalars — at an identical 3,472 schema bytes either way. Measured
    # against the live API; see the module docstring. Keep new nested models in
    # this block and new scalars below it.
    compensation: Compensation = Field(default_factory=Compensation)
    location: Location = Field(default_factory=Location)
    eligibility: EligibilitySignals = Field(default_factory=EligibilitySignals)
    visa: VisaSignals = Field(default_factory=VisaSignals)

    # ---- Scalars ----
    title_normalized: str
    company_canonical: str
    seniority: Seniority = Seniority.UNKNOWN
    remote_policy: RemotePolicy = RemotePolicy.UNKNOWN

    skills: list[str] = Field(default_factory=list)
    skills_unmapped: list[str] = Field(default_factory=list)
    required_quals: list[str] = Field(default_factory=list)
    preferred_quals: list[str] = Field(default_factory=list)

    language: str = "en"
    extraction_confidence: float = Field(0.5, ge=0.0, le=1.0)
