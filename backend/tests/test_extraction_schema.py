"""JobComponents validation — especially the rules structured outputs cannot
enforce: ranking-critical claims need verbatim evidence, comp needs a currency."""

import pytest
from pydantic import ValidationError

from app.extraction.schema import (
    Compensation,
    CompPeriod,
    EligibilitySignals,
    JobComponents,
    RemotePolicy,
    Seniority,
    VisaSignals,
)


def _minimal(**overrides):
    base = {
        "title_raw": "Software Engineer",
        "title_normalized": "Software Engineer",
        "company_raw": "Acme Inc.",
        "company_canonical": "Acme",
    }
    base.update(overrides)
    return JobComponents(**base)


class TestVisaSignals:
    def test_all_null_needs_no_evidence(self):
        """The common case: the posting says nothing about work authorization."""
        visa = VisaSignals()
        assert visa.any_flag_set is False
        assert visa.evidence == []

    @pytest.mark.parametrize(
        "flag",
        [
            "sponsorship_available",
            "requires_existing_authorization",
            "citizenship_or_pr_required",
        ],
    )
    def test_any_flag_without_evidence_is_rejected(self, flag):
        with pytest.raises(ValidationError, match="verbatim evidence"):
            VisaSignals(**{flag: True})

    def test_false_also_requires_evidence(self):
        """False is a claim about the posting too — "says it does NOT sponsor"
        needs a quote just as much as True does."""
        with pytest.raises(ValidationError, match="verbatim evidence"):
            VisaSignals(sponsorship_available=False)

    def test_blank_evidence_does_not_satisfy_the_rule(self):
        with pytest.raises(ValidationError, match="verbatim evidence"):
            VisaSignals(sponsorship_available=True, evidence=["", "   "])

    def test_flag_with_evidence_is_accepted(self):
        visa = VisaSignals(
            sponsorship_available=True,
            evidence=["We are able to sponsor work permits for this role."],
        )
        assert visa.any_flag_set is True

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            VisaSignals(sponsorship_maybe=True)  # type: ignore[call-arg]


class TestCompensation:
    def test_empty_is_valid(self):
        assert Compensation().min_amount is None

    def test_amount_without_currency_rejected(self):
        """A bare number is ambiguous between CAD and USD in Canadian postings
        and unusable downstream."""
        with pytest.raises(ValidationError, match="require a currency"):
            Compensation(min_amount=120_000, period=CompPeriod.YEAR)

    def test_inverted_range_rejected(self):
        with pytest.raises(ValidationError, match="exceeds max_amount"):
            Compensation(
                min_amount=200_000, max_amount=100_000, currency="CAD", period=CompPeriod.YEAR
            )

    def test_valid_range(self):
        comp = Compensation(
            min_amount=120_000, max_amount=150_000, currency="CAD", period=CompPeriod.YEAR
        )
        assert comp.is_estimated is False

    def test_currency_alone_is_fine(self):
        # "salary in CAD" with no figures shouldn't fail
        assert Compensation(currency="CAD").min_amount is None


class TestJobComponents:
    def test_minimal_posting_gets_safe_defaults(self):
        c = _minimal()
        assert c.seniority is Seniority.UNKNOWN
        assert c.remote_policy is RemotePolicy.UNKNOWN
        assert c.skills == [] and c.skills_unmapped == []
        assert c.visa.any_flag_set is False
        assert c.language == "en"
        assert c.extraction_confidence == 0.5

    def test_confidence_bounds_enforced(self):
        with pytest.raises(ValidationError):
            _minimal(extraction_confidence=1.4)
        with pytest.raises(ValidationError):
            _minimal(extraction_confidence=-0.1)

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            _minimal(salary_guess=100)

    def test_invalid_seniority_rejected(self):
        with pytest.raises(ValidationError):
            _minimal(seniority="principal")

    def test_json_schema_is_generatable(self):
        """Structured outputs need a JSON schema — if this raises, the API call
        cannot be made at all."""
        schema = JobComponents.model_json_schema()
        assert "title_raw" in schema["properties"]
        assert "visa" in schema["properties"]


class TestEligibilitySignals:
    def test_empty_is_valid(self):
        e = EligibilitySignals()
        assert e.any_gate_set is False
        assert e.min_years_experience is None

    def test_experience_claim_requires_evidence(self):
        """min_years_experience is what the feed ranks on — a fabricated "5+
        years" wrongly excludes a user from a role they could have got."""
        with pytest.raises(ValidationError, match="verbatim evidence"):
            EligibilitySignals(min_years_experience=5)

    def test_experience_with_evidence_accepted(self):
        e = EligibilitySignals(
            min_years_experience=5, evidence=["5+ years of professional experience"]
        )
        assert e.any_gate_set is True

    def test_blank_evidence_does_not_satisfy_the_rule(self):
        with pytest.raises(ValidationError, match="verbatim evidence"):
            EligibilitySignals(min_years_experience=3, evidence=["  "])

    def test_booleans_do_not_require_evidence(self):
        """Lower stakes than the experience number, and requiring quotes for
        every boolean would push the model to fabricate them."""
        e = EligibilitySignals(is_new_grad_friendly=True, french_required=False)
        assert e.any_gate_set is True

    @pytest.mark.parametrize("years", [-1, 41])
    def test_absurd_experience_values_rejected(self, years):
        with pytest.raises(ValidationError):
            EligibilitySignals(min_years_experience=years, evidence=["x"])

    def test_zero_years_is_meaningful_not_falsy(self):
        """0 must survive: "no experience required" is a real, useful signal and
        a falsy-check would drop it."""
        e = EligibilitySignals(min_years_experience=0, evidence=["No experience required"])
        assert e.min_years_experience == 0
        assert e.any_gate_set is True

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            EligibilitySignals(vibes_required=True)  # type: ignore[call-arg]


def test_job_components_carries_eligibility():
    c = _minimal(
        eligibility=EligibilitySignals(
            min_years_experience=2, evidence=["2+ years experience"], is_new_grad_friendly=True
        )
    )
    assert c.eligibility.min_years_experience == 2
    elig_schema = JobComponents.model_json_schema()["$defs"]["EligibilitySignals"]
    assert "min_years_experience" in elig_schema["properties"]
