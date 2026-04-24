"""Unit tests for the NLP skill extractor."""
import pytest
from app.services.nlp import extract_skills


def test_extracts_known_skills():
    text = "We need a Python developer with React and PostgreSQL experience."
    skills = extract_skills(text)
    assert "python" in skills
    assert "react" in skills
    assert "postgresql" in skills


def test_returns_sorted_deduplicated():
    text = "python python python react react"
    skills = extract_skills(text)
    assert skills == sorted(set(skills))
    assert skills.count("python") == 1
    assert skills.count("react") == 1


def test_case_insensitive():
    assert extract_skills("PYTHON and JavaScript") == extract_skills("python and javascript")


def test_empty_string_returns_empty():
    assert extract_skills("") == []


def test_no_skills_in_text():
    assert extract_skills("We are looking for a motivated team player.") == []


def test_multiword_skills():
    text = "Experience with machine learning and deep learning required."
    skills = extract_skills(text)
    assert "machine learning" in skills
    assert "deep learning" in skills


def test_truncates_at_50k_chars():
    # Should not raise; result should still contain skills found in first 50k chars
    long_text = "python developer " * 4000  # ~68k chars
    skills = extract_skills(long_text)
    assert "python" in skills


def test_all_results_are_lowercase():
    skills = extract_skills("TypeScript, AWS, GraphQL")
    assert all(s == s.lower() for s in skills)
