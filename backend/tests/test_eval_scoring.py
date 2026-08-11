"""Unit tests for the eval harness's scoring logic (not the app itself)."""

from pathlib import Path

from eval.scripts.score_extraction import _prf1, score

_FIXTURES = Path(__file__).parent.parent / "eval" / "fixtures" / "smoke_listings.jsonl"


def test_prf1_perfect_match():
    assert _prf1({"python", "react"}, {"python", "react"}) == (1.0, 1.0, 1.0)


def test_prf1_both_empty_is_perfect():
    assert _prf1(set(), set()) == (1.0, 1.0, 1.0)


def test_prf1_no_overlap():
    precision, recall, f1 = _prf1({"python"}, {"react"})
    assert precision == 0.0
    assert recall == 0.0
    assert f1 == 0.0


def test_prf1_partial_overlap():
    precision, recall, f1 = _prf1({"python", "react"}, {"python", "aws"})
    assert precision == 0.5
    assert recall == 0.5
    assert f1 == 0.5


def test_score_against_smoke_fixtures():
    results = score(_FIXTURES)
    assert results.n == 10
    assert results.n_human_verified == 10  # all fixtures are hand-authored gold
    micro_p, micro_r, micro_f1 = results.micro
    # baseline_extractor should do well on hand-picked, in-vocab skills
    assert micro_r == 1.0  # every gold skill is in _SKILLS_VOCAB by construction
    assert micro_p > 0.9  # a couple of known substring false positives (react/react native etc.)
    assert micro_f1 > 0.9
