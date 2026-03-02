# ADR-0013 — Distribution: PyPI + Homebrew

**Status:** Accepted
**Date:** 2026-03
**Context:** How users install innie-engine

---

## Context

innie-engine is a command-line tool for developers. The installation experience should be:
- Simple (one command)
- Reproducible (exact version pinning)
- Accessible to Python users and non-Python users alike

Options considered:

1. **Git clone + pip install** — requires knowing the repo URL
2. **PyPI only** — `pip install innie-engine` — requires Python environment management
3. **Homebrew only** — `brew install ...` — Mac/Linux only, requires tap setup
4. **PyPI + Homebrew** — both channels, different audiences
5. **Docker** — `docker run innie ...` — heavy for a CLI tool, no filesystem access
6. **Standalone binary** — PyInstaller/Nuitka — large binary, harder to maintain

---

## Decision

**Publish to PyPI and create a Homebrew tap, with automated formula updates.**

**PyPI:**
- Package name: `innie-engine`
- Entry point: `innie` command
- Build backend: `hatchling`
- Wheel: pure Python, no compilation required
- Publishing: GitHub Actions trusted publishing (OIDC, no API token stored)

**Homebrew:**
- Tap: `joshuajenquist/tap`
- Formula: `Formula/innie.rb`
- Uses `virtualenv_install_with_resources` pattern
- Install: `brew tap joshuajenquist/tap && brew install innie`
- Auto-update: `update-formula.yml` workflow triggered by `repository_dispatch` from PyPI publish

**Release process:**
```bash
git tag v0.2.0 && git push origin v0.2.0
# → GitHub Actions builds → publishes to PyPI → triggers homebrew-tap update
```

---

## Rationale

**Against git clone + pip install:** Not discoverable. Harder to update. Requires knowing the repo URL.

**Against PyPI only:** Python users are fine with `pip install`. But many developer-tool users (especially on Mac) prefer Homebrew and don't want to manage Python environments. Homebrew installs into a virtualenv automatically.

**Against Homebrew only:** Homebrew is Mac/Linux only. Windows users (and CI environments) would be excluded. Also, PyPI is more convenient for Python projects where users already have a venv.

**Against Docker:** Docker is too heavy for a local CLI tool. The tool needs direct filesystem access to `~/.innie/`, `~/.claude/settings.json`, etc. Docker volume mounting would make this awkward.

**Against standalone binary:** Would require PyInstaller/Nuitka. Larger download. Harder to debug. No benefit for a pure-Python tool.

**For PyPI + Homebrew:**
- PyPI covers Python developers, CI environments, Windows, Linux
- Homebrew covers Mac developers who prefer the brew install pattern
- Two channels, zero user friction for either audience
- Automated formula updates mean Homebrew users get new versions quickly

**Why trusted publishing (OIDC) over API tokens?** PyPI trusted publishing uses GitHub Actions OIDC tokens. No API token needs to be stored as a GitHub secret. The token is short-lived and scoped to the specific repository+workflow+environment. This is the current best practice for PyPI publishing from CI.

**Why auto-update the Homebrew formula?** Manual formula updates are a maintenance burden and a common source of out-of-date Homebrew taps. The `repository_dispatch` pattern (innie-engine sends an event to homebrew-tap after publishing) makes updates automatic and ensures the Homebrew version matches PyPI within minutes of a release.

---

## Consequences

**Positive:**
- Single command install for both Python and Homebrew users
- Automated release pipeline: tag → publish → Homebrew update
- No API tokens stored in CI (OIDC trusted publishing)
- Both channels kept in sync automatically

**Negative:**
- Homebrew tap must be hosted publicly (cannot be private)
- Homebrew formula only works on Mac/Linux (no Windows Homebrew)
- `TAP_GITHUB_TOKEN` secret required in the innie-engine repo for cross-repo dispatch

**Neutral:**
- PyPI package name is `innie-engine` (CLI command is `innie`)
- Homebrew formula name is `innie` (in tap `joshuajenquist/tap`)
- Version bumps require editing `pyproject.toml` version + tagging
