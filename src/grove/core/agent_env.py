"""Two-tier .env loading for grove agents.

Secrets are split across two files:
- ~/.grove/.env          — shared across all agents (GH_TOKEN, GOG_KEYRING_PASSWORD, etc.)
- ~/.grove/agents/<n>/.env — agent-specific (MATTERMOST_BOT_TOKEN, etc.)

Loading order: shared first, then agent-specific. Agent-specific keys win on collision.
Neither file is indexed by search or committed to the ~/.grove git repo.

Format: standard KEY=VALUE, one per line. Comments (#) and blank lines are ignored.
"""

import os
from pathlib import Path

from grove.core import paths


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def load_agent_env(agent: str | None = None) -> dict[str, str]:
    """Load merged env: shared ~/.grove/.env first, then agent-specific (agent wins)."""
    merged = _parse_env_file(paths.shared_env_file())
    merged.update(_parse_env_file(paths.env_file(agent)))
    return merged


def load_shared_env() -> dict[str, str]:
    """Load only the shared ~/.grove/.env."""
    return _parse_env_file(paths.shared_env_file())


def get_env_var(key: str, agent: str | None = None) -> str | None:
    """Get a single env var — checks merged (shared + agent-specific) env."""
    return load_agent_env(agent).get(key)


def set_env_var(key: str, value: str, agent: str | None = None, shared: bool = False) -> None:
    """Set a key in the agent's .env file (or shared file if shared=True), creating if needed."""
    env_path = paths.shared_env_file() if shared else paths.env_file(agent)
    env_path.parent.mkdir(parents=True, exist_ok=True)

    lines = env_path.read_text().splitlines() if env_path.exists() else []

    # Replace existing key or append
    new_lines = []
    found = False
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k == key:
                new_lines.append(f"{key}={value}")
                found = True
                continue
        new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n")


def unset_env_var(key: str, agent: str | None = None, shared: bool = False) -> bool:
    """Remove a key from the agent's .env file (or shared if shared=True). Returns True if existed."""
    env_path = paths.shared_env_file() if shared else paths.env_file(agent)
    if not env_path.exists():
        return False

    lines = env_path.read_text().splitlines()
    new_lines = []
    found = False
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k == key:
                found = True
                continue
        new_lines.append(line)

    if found:
        env_path.write_text("\n".join(new_lines) + "\n")
    return found


def inject_into_os_env(agent: str | None = None) -> None:
    """Inject secrets into os.environ (does not overwrite vars already set, e.g. from launchd).

    Priority (highest first): launchd env > agent-specific .env > shared .env
    We inject agent-specific first so it wins over shared on collision via setdefault.
    """
    for key, value in load_agent_env(agent).items():
        os.environ.setdefault(key, value)
