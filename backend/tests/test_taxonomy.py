"""Taxonomy loads, validates, and normalizes. No network, no DB."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from taxonomy.config import (
    Skill,
    SkillNormalizer,
    Taxonomy,
    get_normalizer,
    load_taxonomy,
    match_key,
)

GOLD = Path(__file__).parent.parent / "eval" / "gold" / "extraction_skills.jsonl"


class TestRealTaxonomy:
    def test_loads_and_respects_the_cap(self):
        tax = load_taxonomy()
        assert tax.version == 1
        # CLAUDE.md caps canonical ids at ~200; a big jump means auto-expansion
        # crept in, which the taxonomy explicitly forbids.
        assert 150 <= len(tax.skills) <= 210

    def test_every_skill_has_a_known_category(self):
        allowed = {
            "language", "frontend", "backend", "mobile", "ml", "data", "database",
            "cloud", "infra", "api", "security", "testing", "tooling", "practice",
            "domain",
        }
        assert {s.category for s in load_taxonomy().skills} <= allowed

    def test_seeded_from_baseline_vocab(self):
        """The taxonomy must still cover the frozen baseline's vocabulary, so
        LLM-vs-baseline eval comparisons stay apples-to-apples."""
        from app.services.nlp import _SKILLS_VOCAB

        norm = get_normalizer()
        unresolved = sorted({v for v in _SKILLS_VOCAB if not norm.resolve(v)})
        # haskell/lua were deliberately dropped at the cap (documented in the
        # YAML); nothing else from the seed may silently disappear.
        assert unresolved == ["haskell", "lua"], unresolved

    @pytest.mark.skipif(not GOLD.exists(), reason="gold set not present")
    def test_beats_baseline_coverage_on_the_gold_set(self):
        """Coverage of real skill mentions must be far above the baseline's
        33% — that gap is the whole point of the taxonomy."""
        norm = get_normalizer()
        rows = [json.loads(line) for line in GOLD.open() if line.strip()]
        mentions = [str(s).lower() for r in rows for s in (r.get("skills") or [])]
        resolved = sum(1 for m in mentions if norm.resolve(m))
        assert resolved / len(mentions) > 0.60


class TestMatchKey:
    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("Node.js", "nodejs"),
            ("NODE JS", "node.js"),
            ("ci/cd", "ci cd"),
            ("CI-CD", "cicd"),
            ("A/B Testing", "ab testing"),
            ("  Python  ", "python"),
            ("scikit-learn", "scikit learn"),
        ],
    )
    def test_equivalent_spellings_share_a_key(self, a, b):
        assert match_key(a) == match_key(b)

    def test_plus_and_hash_are_significant(self):
        # c++ and c# must not collapse into "c"
        assert match_key("c++") != match_key("c#")
        assert match_key("c++") != match_key("c")


class TestNormalizer:
    def test_resolves_aliases_to_canonical_ids(self):
        norm = get_normalizer()
        assert norm.resolve("golang") == "go"
        assert norm.resolve("K8s") == "kubernetes"
        assert norm.resolve("Postgres") == "postgresql"
        assert norm.resolve("Google Cloud Platform") == "gcp"
        assert norm.resolve("LLMs") == "large language models"
        assert norm.resolve("Infrastructure-as-Code") == "infrastructure as code"

    def test_unknown_skill_returns_none(self):
        assert get_normalizer().resolve("cobol on cogs") is None

    def test_blank_returns_none(self):
        norm = get_normalizer()
        assert norm.resolve("") is None
        assert norm.resolve("   ") is None

    def test_normalize_splits_mapped_and_unmapped(self):
        mapped, unmapped = get_normalizer().normalize(
            ["Python", "golang", "Fortran", "  ", "COBOL"]
        )
        assert mapped == ["go", "python"]
        assert unmapped == ["cobol", "fortran"]

    def test_normalize_deduplicates_and_sorts(self):
        mapped, unmapped = get_normalizer().normalize(
            ["Node.js", "nodejs", "NODE JS", "react.js", "React"]
        )
        assert mapped == ["node.js", "react"]
        assert unmapped == []


class TestValidation:
    def test_duplicate_id_rejected(self):
        with pytest.raises(ValidationError, match="duplicate skill id"):
            Taxonomy(
                version=1,
                skills=(
                    Skill(id="python", category="language"),
                    Skill(id="python", category="language"),
                ),
            )

    def test_alias_claimed_by_two_skills_rejected(self):
        """A term mapping to two canonical ids would resolve last-one-wins and
        silently mis-tag listings — this must fail at load time."""
        with pytest.raises(ValidationError, match="maps to both"):
            Taxonomy(
                version=1,
                skills=(
                    Skill(id="debugging", category="practice", aliases=("root cause analysis",)),
                    Skill(
                        id="incident management",
                        category="infra",
                        aliases=("root cause analysis",),
                    ),
                ),
            )

    def test_alias_colliding_with_another_id_rejected(self):
        with pytest.raises(ValidationError, match="maps to both"):
            Taxonomy(
                version=1,
                skills=(
                    Skill(id="go", category="language"),
                    Skill(id="golang", category="language", aliases=("go",)),
                ),
            )

    def test_uppercase_id_rejected(self):
        with pytest.raises(ValidationError, match="lowercase"):
            Skill(id="Python", category="language")

    def test_punctuation_variant_of_an_id_is_a_collision(self):
        with pytest.raises(ValidationError, match="maps to both"):
            Taxonomy(
                version=1,
                skills=(
                    Skill(id="node.js", category="backend"),
                    Skill(id="nodejs", category="backend"),
                ),
            )


def test_normalizer_accepts_a_custom_taxonomy():
    norm = SkillNormalizer(
        Taxonomy(version=1, skills=(Skill(id="widgets", category="domain", aliases=("widget",)),))
    )
    assert norm.resolve("Widget") == "widgets"
    assert norm.resolve("python") is None
