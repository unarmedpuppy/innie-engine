"""Per-agent .env file — load, get, set, unset.

Each agent can have ~/.innie/agents/<name>/.env for secrets (tokens, keys, passwords).
The file is gitignored from the ~/.innie repo and never indexed by search.

Format: standard KEY=VALUE, one per line. Comments (#) and blank lines are ignored.
"""

import os
from pathlib import Path

from innie.core import paths


def load_agent_env(agent: str | None = None) -> dict[str, str]:
    """Load all key=value pairs from the agent's .env file."""
    env_path = paths.env_file(agent)
    if not env_path.exists():
        return {}

    result = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip()
    return result


def get_env_var(key: str, agent: str | None = None) -> str | None:
    """Get a single env var from the agent's .env file."""
    return load_agent_env(agent).get(key)


def set_env_var(key: str, value: str, agent: str | None = None) -> None:
    """Set a key in the agent's .env file, creating it if needed."""
    env_path = paths.env_file(agent)
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


def unset_env_var(key: str, agent: str | None = None) -> bool:
    """Remove a key from the agent's .env file. Returns True if it existed."""
    env_path = paths.env_file(agent)
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
    """Load the agent's .env and inject into os.environ (does not overwrite existing vars)."""
    for key, value in load_agent_env(agent).items():
        os.environ.setdefault(key, value)
