"""Load skills.yaml and normalize free-form skill strings to canonical ids.

The extractor emits whatever phrasing a job posting uses; this maps that to
the reviewed vocabulary so counts aggregate correctly ("Node.js", "nodejs"
and "NODE JS" are one skill). Anything unmatched is reported as unmapped for
weekly review rather than silently invented into the taxonomy.
"""

import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

_DEFAULT_PATH = Path(__file__).parent / "skills.yaml"

# Separators are deleted rather than collapsed to a space, because spacing is
# itself inconsistent in the wild: "node.js" / "nodejs" / "Node JS" and
# "ci/cd" / "ci-cd" / "CI CD" are each one skill. `+` and `#` are kept —
# they're the only thing distinguishing c++, c# and c.
_INSIGNIFICANT = re.compile(r"[^a-z0-9+#]+")


def match_key(raw: str) -> str:
    """Normalization key for comparing two skill spellings."""
    return _INSIGNIFICANT.sub("", raw.strip().lower())


class Skill(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    category: str
    aliases: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _lowercase_ids(self) -> "Skill":
        if self.id != self.id.lower().strip():
            raise ValueError(f"skill id must be lowercase and trimmed: {self.id!r}")
        return self


class Taxonomy(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int
    skills: tuple[Skill, ...]

    @model_validator(mode="after")
    def _check_unique(self) -> "Taxonomy":
        seen_ids: set[str] = set()
        # match key -> what it already resolves to, so a duplicate alias is a
        # load-time error rather than a silent last-one-wins.
        seen_keys: dict[str, str] = {}
        for skill in self.skills:
            if skill.id in seen_ids:
                raise ValueError(f"duplicate skill id: {skill.id}")
            seen_ids.add(skill.id)
            for term in (skill.id, *skill.aliases):
                key = match_key(term)
                if key in seen_keys and seen_keys[key] != skill.id:
                    raise ValueError(
                        f"'{term}' maps to both '{seen_keys[key]}' and '{skill.id}'"
                    )
                seen_keys[key] = skill.id
        return self

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(s.id for s in self.skills)


class SkillNormalizer:
    """Resolves raw skill strings to canonical ids."""

    def __init__(self, taxonomy: Taxonomy) -> None:
        self.taxonomy = taxonomy
        self._by_key: dict[str, str] = {}
        for skill in taxonomy.skills:
            for term in (skill.id, *skill.aliases):
                self._by_key[match_key(term)] = skill.id

    def resolve(self, raw: str) -> str | None:
        """Canonical id for `raw`, or None if it isn't in the taxonomy."""
        if not raw or not raw.strip():
            return None
        return self._by_key.get(match_key(raw))

    def normalize(self, raw_skills: list[str]) -> tuple[list[str], list[str]]:
        """Split raw skills into (canonical ids, unmapped originals).

        Canonical ids are deduplicated and sorted so two orderings of the same
        skill set produce identical rows. Unmapped strings are lowercased and
        deduplicated for the review queue.
        """
        mapped: set[str] = set()
        unmapped: set[str] = set()
        for raw in raw_skills:
            canonical = self.resolve(raw)
            if canonical:
                mapped.add(canonical)
            elif raw.strip():
                unmapped.add(raw.strip().lower())
        return sorted(mapped), sorted(unmapped)


def load_taxonomy(path: Path = _DEFAULT_PATH) -> Taxonomy:
    with path.open() as f:
        return Taxonomy.model_validate(yaml.safe_load(f))


@lru_cache
def get_normalizer() -> SkillNormalizer:
    """Process-wide normalizer (the YAML is static at runtime)."""
    return SkillNormalizer(load_taxonomy())
