"""JobComponents validation — especially the rules structured outputs cannot
enforce: ranking-critical claims need verbatim evidence, comp needs a currency."""

import pytest
from pydantic import ValidationError

from app.extraction.schema import (
    Compensation,
    CompPeriod,
    EligibilitySignals,
    JobComponents,
    Location,
    RemotePolicy,
    Seniority,
    Stated,
    VisaSignals,
)


def _minimal(**overrides):
    base = {
        "title_normalized": "Software Engineer",
        "company_canonical": "Acme",
    }
    base.update(overrides)
    return JobComponents(**base)


class TestVisaSignals:
    def test_not_stated_needs_no_evidence(self):
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
            VisaSignals(**{flag: Stated.YES})

    def test_no_also_requires_evidence(self):
        """NO is a claim about the posting too — "says it does NOT sponsor"
        needs a quote just as much as YES does."""
        with pytest.raises(ValidationError, match="verbatim evidence"):
            VisaSignals(sponsorship_available=Stated.NO)

    def test_blank_evidence_does_not_satisfy_the_rule(self):
        with pytest.raises(ValidationError, match="verbatim evidence"):
            VisaSignals(sponsorship_available=Stated.YES, evidence=["", "   "])

    def test_flag_with_evidence_is_accepted(self):
        visa = VisaSignals(
            sponsorship_available=Stated.YES,
            evidence=["We are able to sponsor work permits for this role."],
        )
        assert visa.any_flag_set is True

    def test_extra_fields_rejected(self):
        with pytest.raises(ValidationError):
            VisaSignals(sponsorship_maybe=Stated.YES)  # type: ignore[call-arg]


class TestStated:
    """The enum that replaced `bool | None` to stay inside the API's union
    ceiling — `to_bool` is what keeps the DB columns genuinely tri-state."""

    def test_round_trips_to_the_column_values(self):
        assert Stated.YES.to_bool() is True
        assert Stated.NO.to_bool() is False
        assert Stated.NOT_STATED.to_bool() is None

    def test_not_stated_is_the_default_everywhere(self):
        assert VisaSignals().sponsorship_available is Stated.NOT_STATED
        assert EligibilitySignals().degree_required is Stated.NOT_STATED


class TestCompensation:
    def test_empty_is_valid(self):
        # 0 is the "unstated" sentinel: a union here would cost schema budget.
        assert Compensation().min_amount == 0.0
        assert Compensation().has_amount is False

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
        assert Compensation(currency="CAD").has_amount is False


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
        assert "title_normalized" in schema["properties"]
        assert "visa" in schema["properties"]

    def test_fields_that_duplicate_raw_listings_are_absent(self):
        """Regression guard on schema budget. These four are known from the
        board API; asking the model to echo them is what pushed the schema past
        the API's complexity ceiling, and it returned worse values than the
        source. `_to_row` fills the columns from the raw row instead."""
        props = JobComponents.model_json_schema()["properties"]
        for dropped in ("title_raw", "company_raw", "location_raw", "posted_at"):
            assert dropped not in props

    def test_geo_is_nested_to_save_top_level_width(self):
        """city/region/country as three top-level scalars does not compile —
        see the module docstring in schema.py for the measurement."""
        c = _minimal(location=Location(city="Toronto", region="ON", country="CA"))
        assert c.location.city == "Toronto"
        assert "location" in JobComponents.model_json_schema()["properties"]


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
        e = EligibilitySignals(
            is_new_grad_friendly=Stated.YES, french_required=Stated.NO
        )
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
            EligibilitySignals(vibes_required=Stated.YES)  # type: ignore[call-arg]


def test_job_components_carries_eligibility():
    c = _minimal(
        eligibility=EligibilitySignals(
            min_years_experience=2,
            evidence=["2+ years experience"],
            is_new_grad_friendly=Stated.YES,
        )
    )
    assert c.eligibility.min_years_experience == 2
    elig_schema = JobComponents.model_json_schema()["$defs"]["EligibilitySignals"]
    assert "min_years_experience" in elig_schema["properties"]
