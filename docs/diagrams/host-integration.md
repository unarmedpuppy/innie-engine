# Host Integration Diagram

What touches the host system, where it lives, and how it's controlled.

---

## Host Filesystem Map

```
Host Filesystem
│
├── ~/.innie/                               ← ALL innie data (isolated)
│   ├── config.toml                         ← global config
│   ├── user.md                             ← your profile
│   ├── fleet.yaml                          ← fleet config (optional)
│   ├── hooks/                              ← bash shim scripts
│   │   ├── session-start.sh               ← installed by innie backend install
│   │   ├── pre-compact.sh
│   │   ├── stop.sh
│   │   └── post-tool-use.sh
│   └── agents/
│       └── innie/                          ← isolated agent data
│           └── (see Storage Layout)
│
├── ~/.claude/settings.json                 ← MODIFIED (namespace-safe)
│   └── hooks → points to ~/.innie/hooks/  ← ONLY innie's own hooks added
│
├── ~/.cursor/ (settings files)             ← MODIFIED (namespace-safe, if cursor)
│
├── ~/.zshrc or ~/.bashrc                   ← APPENDED (only if innie alias is run)
│   └── alias innie="..."                  ← opt-in only
│
└── crontab                                 ← NOT modified (user sets up manually)
```

---

## Backend Hook Wiring

```mermaid
flowchart TD
    subgraph BACKEND_CFG["~/.claude/settings.json"]
        H_START["hooks.SessionStart\n→ ~/.innie/hooks/session-start.sh"]
        H_COMPACT["hooks.PreCompact\n→ ~/.innie/hooks/pre-compact.sh"]
        H_STOP["hooks.Stop\n→ ~/.innie/hooks/stop.sh"]
        H_TOOL["hooks.PostToolUse\n→ ~/.innie/hooks/post-tool-use.sh"]
    end

    subgraph SHIMS["~/.innie/hooks/"]
        S_START["session-start.sh\n#!/bin/bash\ninnie init --event session-start"]
        S_COMPACT["pre-compact.sh\n#!/bin/bash\ninnie init --event pre-compact"]
        S_STOP["stop.sh\n#!/bin/bash\ninnie init --event stop"]
        S_TOOL["post-tool-use.sh\n#!/bin/bash\ninnie init --event post-tool-use"]
    end

    subgraph HANDLERS["innie CLI handlers"]
        H1["context.build_session_context()\n→ returns XML block to stdout"]
        H2["context.build_precompact_warning()\n→ returns warning to stdout"]
        H3["save session log\n→ state/sessions/YYYY-MM-DD.md"]
        H4["append to trace\n→ state/trace/YYYY-MM-DD.jsonl"]
    end

    H_START --> S_START --> H1
    H_COMPACT --> S_COMPACT --> H2
    H_STOP --> S_STOP --> H3
    H_TOOL --> S_TOOL --> H4
```

---

## Isolation Boundaries

```
┌──────────────────────────────────────────────────────────────┐
│                        HOST SYSTEM                            │
│                                                              │
│  AI Tool Config (r/w, namespace-safe)                        │
│  └── ~/.claude/settings.json                                 │
│  └── ~/.cursor/ settings                                     │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              INNIE-ENGINE ISOLATION BOUNDARY           │  │
│  │                                                        │  │
│  │  ~/.innie/                                             │  │
│  │  ├── config.toml           (innie reads/writes)        │  │
│  │  ├── hooks/                (innie owns, tool executes) │  │
│  │  └── agents/               (innie reads/writes)        │  │
│  │      └── <name>/                                       │  │
│  │          ├── data/         ← git-trackable, permanent  │  │
│  │          └── state/        ← ephemeral, rebuildable    │  │
│  │                                                        │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  Git (user's repos)                                          │
│  └── read-only: git log, git diff  (heartbeat collect)       │
│  └── write: ~/.innie/agents/*/data/  (only with auto_commit) │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## Network Surface

```
                              Internet
                                 │
                    (if auto_push = true)
                                 │
                              ┌──┴──┐
                              │ Git │  (e.g., GitHub / Gitea)
                              └─────┘

                              Tailscale / LAN
                                 │
                    ┌────────────┴────────────┐
                    │                         │
            ┌───────┴──────┐        ┌─────────┴──────┐
            │ innie serve  │        │ innie fleet    │
            │   :8013      │        │   :8020        │
            │ Jobs API     │        │ Fleet gateway  │
            │ Memory API   │        │ (aggregates)   │
            └──────────────┘        └────────────────┘
                    │
                    ▼
              localhost:8766
           Embedding Service
           (Docker, bge-base-en)
```

**Default: innie has NO network surface.** `innie serve` and `innie fleet start` are opt-in.

---

## What Gets Backed Up to Git

When `git.auto_commit = true`:

```
Committed to git (data/)                    NOT committed (state/)
─────────────────────────────────────────  ─────────────────────────
data/journal/YYYY/MM/DD.md                 state/sessions/*.md
data/learnings/**/*.md                     state/trace/*.jsonl
data/meetings/*.md                         state/.index/memory.db
data/people/*.md                           state/heartbeat-state.json
data/decisions/*.md
data/projects/*.md
data/inbox/inbox.md
SOUL.md
CONTEXT.md
profile.yaml
HEARTBEAT.md
```

The `.gitignore` in the agent's data directory excludes `state/` explicitly.

---

## Uninstall Footprint

Running `innie backend uninstall` leaves the system in this state:

| Location | After uninstall |
|---|---|
| `~/.innie/` | Untouched (your data) |
| `~/.claude/settings.json` | innie hooks removed, user hooks preserved |
| `~/.zshrc` | alias line removed (if `innie alias` was run) |
| Crontab | Not modified (user added manually) |

Complete removal: `rm -rf ~/.innie` after uninstalling hooks.
