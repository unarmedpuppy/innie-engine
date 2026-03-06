"""TOML config loader for innie-engine."""

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]


_cache: dict[str, Any] | None = None


def load_config(path: Path | None = None) -> dict[str, Any]:
    global _cache
    if _cache is not None and path is None:
        return _cache

    if path is None:
        from innie.core.paths import config_file

        path = config_file()

    if not path.exists():
        return {}

    try:
        with open(path, "rb") as f:
            cfg = tomllib.load(f)
    except Exception as e:
        import sys as _sys

        print(f"[innie] config error in {path}: {e}", file=_sys.stderr)
        return {}

    # Cache only when we loaded from the default path
    if _cache is None:
        from innie.core.paths import config_file

        if path == config_file():
            _cache = cfg
    return cfg


def clear_cache() -> None:
    global _cache
    _cache = None


def get(key: str, default: Any = None) -> Any:
    """Dot-notation access: get('embedding.provider', 'docker')"""
    cfg = load_config()
    parts = key.split(".")
    node = cfg
    for part in parts:
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node


DEFAULT_CONFIG = """\
[user]
name = ""
timezone = "UTC"

[defaults]
agent = "innie"

[embedding]
provider = "docker"           # docker | external | none
model = "bge-base-en"

[embedding.docker]
url = "http://localhost:8766"

[embedding.external]
# url = "http://localhost:11434/v1"
# api_key_env = "OPENAI_API_KEY"
# model = "text-embedding-3-small"

[heartbeat]
enabled = false
interval = "30m"
provider = "auto"             # auto | openclaw | anthropic | external
model = "auto"                # model name, or "auto" to pick per provider
external_url = ""             # OpenAI-compatible endpoint (vLLM, Ollama, etc.)
collect_git = true
collect_sessions = true

[index]
chunk_words = 300
chunk_overlap = 60
chunk_markdown_aware = true

[context]
max_tokens = 2000

[git]
auto_commit = false         # Auto-commit data/ after heartbeat
auto_push = false           # Auto-push after commit (requires remote)

[search]
query_expansion = false
expansion_model = "auto"

[update]
source = ""                 # git URL or local path — set by `innie init`
installer = "uv"            # uv | pip
"""
