# ADR-0007 — Git Auto-Backup Integration

**Status:** Accepted
**Date:** 2026-02
**Context:** How the knowledge base survives machine loss

---

## Context

The knowledge base in `data/` is valuable and irreplaceable. Users need a way to ensure it survives:
- Hardware failure
- Accidental `rm -rf`
- Machine migration

Options considered:

1. **No backup** — user responsibility entirely
2. **Automatic tar/zip archives** — zip `data/` on a schedule
3. **Cloud sync (iCloud/Dropbox)** — rely on system-level sync
4. **rsync to remote** — push to a backup server
5. **Git auto-commit** — `data/` is a git repo, committed after each heartbeat
6. **Git auto-commit + push** — commit and push to a remote

---

## Decision

**Git auto-commit (opt-in), with optional auto-push.**

Controlled by two config flags:
```toml
[git]
auto_commit = false   # git add -A && git commit in data/ after each heartbeat
auto_push = false     # git push after commit
```

When enabled, the heartbeat's Phase 3 runs:
```bash
git -C ~/.innie/agents/<name>/data add -A
git -C ~/.innie/agents/<name>/data commit -m "heartbeat: 2026-03-02 14:30"
# if auto_push:
git push
```

The init wizard offers to set up a `.gitignore` and `git init` in the agent directory when git backup is chosen.

---

## Rationale

**Against no backup:** Knowledge bases are the whole value of the system. Loss is catastrophic.

**Against tar/zip:** Archives grow unboundedly. No deduplication. No history. No merging from multiple machines.

**Against iCloud/Dropbox:** Requires platform-specific setup. Sync conflicts with multiple machines. Can't exclude `state/` cleanly.

**Against rsync:** Requires a server with SSH access. One-directional (no pull). No history.

**For git auto-commit:**
- Users already have Git and understand it
- Full history — see every heartbeat's changes with `git log`
- Remote options are unlimited (GitHub, Gitea, bare repo on NAS)
- Conflict resolution with standard `git pull` if used from multiple machines
- The `.gitignore` naturally excludes `state/` and `*.env` files

**Why opt-in?** Forcing git setup on users without a remote configured would create commits that pile up locally with no benefit. Making it opt-in means only users who have configured a remote (or want local history) enable it. The init wizard makes it easy to set up during initialization.

---

## Consequences

**Positive:**
- Full history of knowledge base changes
- Works with any git remote (GitHub, Gitea, bare repo, local)
- `state/` excluded by gitignore — only permanent knowledge is backed up
- Human-readable commit history: every heartbeat is a commit

**Negative:**
- Requires git to be installed (universal but not guaranteed)
- Requires a remote to be configured for `auto_push` to be useful
- Merge conflicts possible if editing the same knowledge base from multiple machines

**Neutral:**
- Commit message format: `"heartbeat: YYYY-MM-DD HH:MM"` — consistent and parseable
- Users can also manually commit/push at any time — the auto-commit just ensures it happens
