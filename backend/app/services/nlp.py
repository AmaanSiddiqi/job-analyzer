"""
Skill extractor using spaCy PhraseMatcher.

The model is loaded once at import time. `extract_skills(text)` is the
only public function — it returns a sorted, deduplicated list of lowercase
skill strings found in the text.
"""

import spacy
from spacy.matcher import PhraseMatcher

# ---------------------------------------------------------------------------
# Vocabulary — extend this list as needed
# ---------------------------------------------------------------------------
_SKILLS_VOCAB: list[str] = [
    # Languages
    "python", "javascript", "typescript", "java", "go", "golang", "rust",
    "c++", "c#", "ruby", "php", "swift", "kotlin", "scala", "r", "bash",
    "shell", "perl", "elixir", "haskell", "lua",
    # Web frameworks / libraries
    "react", "vue", "angular", "next.js", "nuxt", "svelte", "jquery",
    "fastapi", "django", "flask", "express", "node.js", "rails",
    "spring boot", "spring", "asp.net", "laravel", "fastify",
    # Mobile
    "react native", "flutter", "ios", "android", "xamarin",
    # Data / ML
    "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "keras",
    "xgboost", "lightgbm", "hugging face", "transformers", "spacy",
    "nlp", "computer vision", "machine learning", "deep learning",
    "data science", "feature engineering", "model deployment",
    # Data engineering
    "spark", "hadoop", "kafka", "airflow", "dbt", "flink",
    "etl", "data pipeline", "data warehouse",
    # Databases
    "postgresql", "postgres", "mysql", "sqlite", "mongodb", "redis",
    "elasticsearch", "cassandra", "dynamodb", "bigquery", "snowflake",
    "supabase", "firebase",
    # Cloud & infra
    "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "k8s",
    "terraform", "ansible", "helm", "cloudformation", "pulumi",
    "ci/cd", "github actions", "gitlab ci", "jenkins", "circleci",
    "linux", "nginx", "apache",
    # APIs & protocols
    "rest", "graphql", "grpc", "websockets", "oauth", "jwt",
    "openapi", "swagger",
    # Version control / collaboration
    "git", "github", "gitlab", "bitbucket", "jira", "confluence",
    # Testing
    "pytest", "jest", "cypress", "selenium", "playwright",
    "unit testing", "integration testing", "tdd",
    # General
    "microservices", "event-driven", "serverless", "agile", "scrum",
    "system design", "distributed systems", "high availability",
]

# ---------------------------------------------------------------------------
# Build the matcher once at module load
# ---------------------------------------------------------------------------
_nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
_matcher = PhraseMatcher(_nlp.vocab, attr="LOWER")
_patterns = list(_nlp.tokenizer.pipe(_SKILLS_VOCAB))
_matcher.add("SKILLS", _patterns)

# Map lowercase → canonical form stored in DB
_canonical: dict[str, str] = {s.lower(): s.lower() for s in _SKILLS_VOCAB}


def extract_skills(text: str) -> list[str]:
    """
    Return a sorted, deduplicated list of lowercase skills found in `text`.
    Matches are case-insensitive (PhraseMatcher attr=LOWER).
    """
    if not text:
        return []
    doc = _nlp(text[:50_000])  # guard against enormous descriptions
    matches = _matcher(doc)
    found = {doc[start:end].text.lower() for _, start, end in matches}
    return sorted(found)
