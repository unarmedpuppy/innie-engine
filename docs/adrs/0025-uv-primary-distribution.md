# ADR-0025 — uv as Primary Distribution Method

- **Date:** 2026-03-02
- **Status:** Accepted (supersedes ADR-0013)
- **Repos/Services affected:** innie-engine

## Context

ADR-0013 planned for PyPI + Homebrew tap distribution. After building the tool and evaluating the options, we decided against Homebrew and made `uv tool install` the primary distribution method.

## Decision

Recommend `uv tool install` as the primary install method. Support `pip install` as a fallback. Do not maintain a Homebrew tap.

```bash
# Primary: uv (recommended)
uv tool install git+https://github.com/joshuajenquist/innie-engine.git

# Editable for development
uv tool install -e ~/workspace/innie-engine

# Fallback: pip
pip install git+https://github.com/joshuajenquist/innie-engine.git
```

## Options Considered

### Option A: PyPI + Homebrew (ADR-0013)
Publish to PyPI for `pip install innie-engine`, maintain a Homebrew tap for `brew install innie`. Maximum discoverability but significant maintenance overhead.

**Why we moved away:**
- Public Homebrew requires 75+ GitHub stars, 30+ forks, or being "notable"
- A personal Homebrew tap requires maintaining a separate `homebrew-tap` repo with formula updates on every release
- Formula must pin exact version, SHA256 hash, and dependency versions
- Python Homebrew formulas are notoriously fragile (virtualenv conflicts)

### Option B: PyPI only
Publish to PyPI for `pip install innie-engine`. Lower bar than Homebrew but still requires: PyPI account, release workflow, version management, and dealing with PyPI's upload mechanics.

### Option C: uv tool install from git (selected)
`uv tool install` installs Python CLI tools in isolated virtual environments with binary shims on PATH. It handles dependencies, Python version management, and isolation automatically.

Advantages:
- Zero publishing infrastructure needed
- Install directly from git (Gitea, GitHub, or local path)
- Isolated venv per tool — no dependency conflicts
- `uv tool update` handles upgrades
- Works offline from local clones

For PyPI publishing later (open source), the pyproject.toml is already configured — just `uv build && uv publish`.

### Option D: Nix flake
Would provide perfect reproducibility but the Nix learning curve is steep and it's not a common tool in the target audience.

## Consequences

### Positive
- Zero publishing infrastructure to maintain
- Install from any git source (Gitea, GitHub, local)
- Users get isolated environments automatically
- Upgrade is `uv tool install --upgrade`
- Editable installs (`-e`) for development

### Negative / Tradeoffs
- Requires uv to be installed first (one extra step)
- Not discoverable via `pip search` or `brew search`
- Private Gitea repos require SSH key access

### Risks
- uv is relatively new (Astral, Rust-based). If it loses momentum, pip remains as fallback. Mitigated by keeping pyproject.toml standard — the package works with any PEP 517 installer.
