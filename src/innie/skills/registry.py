"""Skill registry — discover and execute skills from agents/skills/ directories."""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from innie.core import paths

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _extract_description(content: str) -> str:
    """Extract description from SKILL.md — frontmatter field first, then first body paragraph."""
    m = _FRONTMATTER_RE.match(content)
    if m:
        for line in m.group(1).splitlines():
            if line.startswith("description:"):
                raw = line[len("description:"):].strip().strip('"').strip("'")
                if raw:
                    return raw
        # Frontmatter present but no description field — fall through to body
        body = content[m.end():]
    else:
        body = content

    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return ""


@dataclass
class Skill:
    name: str
    path: Path
    description: str = ""
    template: str = ""


def discover_skills(agent: str | None = None) -> dict[str, Skill]:
    """Find all skills in the agent's skills/ directory."""
    skills_dir = paths.skills_dir(agent)
    skills: dict[str, Skill] = {}

    if not skills_dir.exists():
        return skills

    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        name = skill_dir.name
        content = skill_md.read_text()

        # Extract description — prefer YAML frontmatter description field,
        # fall back to first non-header line of markdown body.
        desc = _extract_description(content)

        skills[name] = Skill(
            name=name,
            path=skill_dir,
            description=desc,
            template=content,
        )

    return skills


def get_skill(name: str, agent: str | None = None) -> Skill | None:
    """Get a specific skill by name."""
    skills = discover_skills(agent)
    return skills.get(name)
