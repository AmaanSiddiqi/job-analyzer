"""Versioned extraction prompts.

PROMPT_VERSION is stored on every extracted row. Changing the prompt text
requires bumping it, re-running the eval, and reporting the F1 delta before
any backfill (CLAUDE.md). Old rows keep their version so a regression is
attributable.
"""

from taxonomy.config import load_taxonomy

PROMPT_VERSION = "v1"

_SYSTEM = """You extract structured data from job postings for a Canadian job-search product whose users are international students and new graduates. Accuracy about work authorization is the single most important thing you do: these users make application decisions based on it.

Rules:

1. Extract only what the posting states. If a field is not stated, leave it null (or an empty list). Never infer, never fill from typical practice for that company or role.

2. Compensation: only report figures the posting actually prints. No estimating from role or market. If no currency is stated alongside a number, report no compensation at all rather than guessing between CAD and USD.

3. Visa signals are tri-state and each one needs proof:
   - true  = the posting says it
   - false = the posting says the opposite
   - null  = the posting does not address it (this is the common case)
   For every flag you set to true or false, copy the exact sentence or phrase from the posting into `evidence`, verbatim and unedited. If you cannot quote it, the flag must be null. Do not treat generic equal-opportunity or background-check language as a work-authorization statement.
   Common genuine phrasings: "we sponsor work permits", "visa sponsorship available", "must be legally entitled to work in Canada", "must be authorized to work in Canada without sponsorship", "Canadian citizenship or permanent residence required", "security clearance eligibility required".

4. Skills: use ids from the canonical skill list below for anything that appears there. Put skills the posting asks for that are absent from the list into `skills_unmapped`, written as the posting writes them. Do not squeeze a skill into a canonical id that does not actually match it.

5. Non-English postings: extract normally and set `language` to the right ISO-639-1 code. Do not translate the evidence quotes — they must stay verbatim.

6. Truncated or garbled postings: extract whatever is legible and set `extraction_confidence` low. Do not reconstruct missing content.

Canonical skill ids (use these exact strings in `skills`):
{skill_ids}"""


def system_prompt() -> str:
    """System prompt with the canonical skill list interpolated.

    The taxonomy is injected rather than hardcoded so adding a skill doesn't
    require editing the prompt — but note that it does change the prompt's
    bytes, so a taxonomy change is also a prompt change for caching purposes.
    """
    ids = sorted(load_taxonomy().ids)
    return _SYSTEM.format(skill_ids=", ".join(ids))


def user_prompt(title: str, company: str, location: str | None, description: str) -> str:
    """Per-listing content. Kept after the system prompt so the large, stable
    prefix (instructions + skill list) is what gets cached."""
    return (
        f"Job title: {title}\n"
        f"Company: {company}\n"
        f"Location as posted: {location or 'not stated'}\n\n"
        f"Posting text:\n{description}"
    )
