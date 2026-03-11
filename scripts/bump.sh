#!/usr/bin/env bash
# bump.sh — semver bump for innie-engine
#
# Usage:
#   scripts/bump.sh patch   # 0.3.0 → 0.3.1
#   scripts/bump.sh minor   # 0.3.1 → 0.4.0
#   scripts/bump.sh major   # 0.4.0 → 1.0.0
#
# What it does:
#   1. Reads current version from pyproject.toml
#   2. Bumps the requested component
#   3. Writes the new version back to pyproject.toml
#   4. Stages pyproject.toml (does NOT commit — leave that to you)
#
# Convention: run this before every commit that changes agent behavior,
# adds features, or fixes bugs. The version is how the fleet knows what
# each agent is running.

set -euo pipefail

PYPROJECT="$(git rev-parse --show-toplevel)/pyproject.toml"

if [[ ! -f "$PYPROJECT" ]]; then
  echo "error: pyproject.toml not found at $PYPROJECT" >&2
  exit 1
fi

BUMP="${1:-patch}"
if [[ "$BUMP" != "patch" && "$BUMP" != "minor" && "$BUMP" != "major" ]]; then
  echo "usage: $0 [patch|minor|major]" >&2
  exit 1
fi

# Extract current version
CURRENT=$(grep '^version = ' "$PYPROJECT" | head -1 | sed 's/version = "\(.*\)"/\1/')
if [[ -z "$CURRENT" ]]; then
  echo "error: could not read version from pyproject.toml" >&2
  exit 1
fi

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"

case "$BUMP" in
  major) MAJOR=$((MAJOR + 1)); MINOR=0; PATCH=0 ;;
  minor) MINOR=$((MINOR + 1)); PATCH=0 ;;
  patch) PATCH=$((PATCH + 1)) ;;
esac

NEW="${MAJOR}.${MINOR}.${PATCH}"

# Update pyproject.toml
sed -i '' "s/^version = \"${CURRENT}\"/version = \"${NEW}\"/" "$PYPROJECT"

echo "${CURRENT} → ${NEW}"

# Stage the version bump
git add "$PYPROJECT"
