"""Versioned extraction prompts.

PROMPT_VERSION is stored on every extracted row. Changing the prompt text
requires bumping it, re-running the eval, and reporting the F1 delta before
any backfill (CLAUDE.md). Old rows keep their version so a regression is
attributable.
"""

from taxonomy.config import load_taxonomy

PROMPT_VERSION = "v3"

_SYSTEM = """You extract structured data from job postings for a Canadian job-search product whose users are international students and new graduates. Accuracy about work authorization is the single most important thing you do: these users make application decisions based on it.

Rules:

1. Extract only what the posting states. Never infer, never fill from typical practice for that company or role. Say "not stated" explicitly rather than guessing — each field has its own way of saying it:
   - yes/no questions (the visa and eligibility flags): "not_stated"
   - enums (`seniority`, `remote_policy`, `compensation.period`): "unknown"
   - text fields (`location.city`, `location.region`, `location.country`, `compensation.currency`): "" (empty string)
   - compensation amounts: 0
   - lists: []
   - `min_years_experience` is the one field that takes a real null.

1b. Eligibility gates are the fields users act on most, so be exact about them. `min_years_experience` is the smallest number of years the posting requires: from "3-5 years" use 3, from "5+ years" use 5, from "minimum 7 years" use 7. If the posting states no number, leave it null — do NOT infer one from the title, because "Senior" in a title and the years in the body frequently disagree and the body is what the recruiter screens on. Quote the requirement verbatim in `eligibility.evidence`. The eligibility flags use the same "yes"/"no"/"not_stated" convention as the visa signals. Set `is_new_grad_friendly` or `is_internship_or_coop` to "yes" only on explicit language ("new grads welcome", "co-op term", "0-2 years"). Set `french_required` to "yes" only where French or bilingualism is actually required, not where the posting merely happens to be bilingual.

2. Compensation: only report figures the posting actually prints. No estimating from role or market. `currency` is an ISO-4217 code ("CAD", "USD"). If no currency is stated alongside a number, report no compensation at all rather than guessing between CAD and USD.

3. Visa signals are three-way and each one needs proof. These are rare in Canadian postings (well under 1%) — that is expected, so "not_stated" is nearly always the right answer, and you should not stretch to find a signal that is not there:
   - "yes"        = the posting says it
   - "no"         = the posting says the opposite
   - "not_stated" = the posting does not address it (this is the common case)
   For every flag you set to "yes" or "no", copy the exact sentence or phrase from the posting into `evidence`, verbatim and unedited. If you cannot quote it, the flag must be "not_stated". Do not treat generic equal-opportunity or background-check language as a work-authorization statement.
   Common genuine phrasings: "we sponsor work permits", "visa sponsorship available", "must be legally entitled to work in Canada", "must be authorized to work in Canada without sponsorship", "Canadian citizenship or permanent residence required", "security clearance eligibility required".

4. Skills: `skills` takes ids from the canonical list below — the exact strings, nothing else. Put skills the posting asks for that are absent from that list into `skills_unmapped`, written as the posting writes them. Do not squeeze a skill into a canonical id that does not actually match it.

5. Non-English postings: extract normally and set `language` to the posting's ISO-639-1 code ("en", "fr"). Do not translate the evidence quotes — they must stay verbatim.

6. Truncated or garbled postings: extract whatever is legible and set `extraction_confidence` low. Do not reconstruct missing content.

7. You are not asked for the raw title, raw company, raw location or posting date — those are already known from the job board's own API and are not yours to repeat. Give the *normalized* title and the canonical company name (drop "Inc.", "Ltd.", "(Canada)" and similar), and parse the location as posted into `location`: `city` as written, `region` as the province or state, `country` as an ISO-3166 alpha-2 code ("CA", "US"). Leave any part you cannot determine as "".

8. Evidence quotes are copied from the posting character for character. Do not paraphrase, trim mid-word, translate, or fix the posting's own typos.

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
