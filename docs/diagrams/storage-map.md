# Storage Map

Visual map of where every piece of data lives, what creates it, and what reads it.

---

## Full Directory Tree with Annotations

```
~/.innie/                               Created by: innie init
│
├── config.toml                         Created by: innie init
│                                       Read by: every command
│                                       Schema: [user] [defaults] [embedding]
│                                                [heartbeat] [index] [git]
│
├── user.md                             Created by: innie init
│                                       Read by: context.py (injected at session start)
│                                       Format: free-form markdown about the user
│
├── fleet.yaml                          Created by: user manually
│                                       Read by: innie fleet start
│                                       Format: YAML agent registry
│
├── hooks/                              Created by: innie backend install
│   ├── session-start.sh               Executed by: AI assistant SessionStart hook
│   ├── dcg-guard.sh                   Executed by: AI assistant PreToolUse hook
│   ├── pre-compact.sh                 Executed by: AI assistant PreCompact hook
│   ├── stop.sh                        Executed by: AI assistant Stop hook
│   └── observability.sh               Executed by: AI assistant PostToolUse hook
│
└── agents/
    └── <name>/                         Created by: innie create <name>
        │
        ├── SOUL.md                     Created by: innie create / innie init
        │                               Read by: context.py at every session start
        │                               Written by: user (manually)
        │                               Content: permanent identity, principles, style
        │
        ├── CONTEXT.md                  Created by: innie create
        │                               Read by: context.py (injected at session start)
        │                               Written by: heartbeat Phase 3 (open_items, focus)
        │                               Written by: decay_context (items removed)
        │                               Content: bounded working memory (~30 day horizon)
        │
        ├── profile.yaml                Created by: innie create
        │                               Read by: profile.load_profile()
        │                               Written by: innie create / profile.save_profile()
        │                               Content: name, role, permissions metadata
        │
        ├── HEARTBEAT.md               Created by: innie create
        │                               Read by: heartbeat Phase 2 (sent to LLM)
        │                               Written by: user (customize extraction)
        │                               Content: instructions for LLM extraction
        │
        ├── skills/                     Created by: innie create
        │   └── <skill-name>/
        │       └── SKILL.md           Created by: user
        │                               Read by: skills/registry.py
        │                               Content: skill template / prompt
        │
        ├── data/                       [PERMANENT — git-trackable]
        │   │
        │   ├── journal/
        │   │   └── YYYY/MM/DD.md      Created by: heartbeat Phase 3 (journal_entries)
        │   │                          Created by: innie skill run daily
        │   │                          Read by: search indexer
        │   │
        │   ├── learnings/
        │   │   └── {category}/
        │   │       └── YYYY-MM-DD-slug.md  Created by: heartbeat Phase 3 (learnings)
        │   │                               Created by: innie skill run learn
        │   │                               Read by: search indexer
        │   │
        │   ├── meetings/
        │   │   └── YYYY-MM-DD-slug.md  Created by: innie skill run meeting
        │   │                           Read by: search indexer
        │   │
        │   ├── people/
        │   │   └── name-slug.md        Created by: innie skill run contact
        │   │                           Read by: search indexer
        │   │
        │   ├── decisions/
        │   │   └── NNNN-slug.md        Created by: innie skill run adr
        │   │                           Created by: heartbeat Phase 3 (decisions)
        │   │                           Read by: search indexer
        │   │
        │   ├── projects/
        │   │   └── project-name.md     Created by: heartbeat Phase 3 (project_updates)
        │   │                           Read by: search indexer
        │   │
        │   ├── inbox/
        │   │   └── inbox.md            Created by: innie skill run inbox (append-only)
        │   │                           Read by: search indexer, user
        │   │
        │   └── metrics/                Created by: user
        │       └── *.md                Read by: search indexer
        │
        └── state/                      [EPHEMERAL — NOT git-tracked]
            │
            ├── sessions/
            │   ├── YYYY-MM-DD.md       Created by: Stop hook (one per day, appended)
            │   └── YYYY-MM-summary.md  Created by: decay_sessions (compresses >90d)
            │                           Read by: heartbeat Phase 1 (collector)
            │
            ├── trace/
            │   ├── traces.db           Created by: innie handle session-init
            │   │                       Written by: innie handle tool-use, session-end
            │   │                       Read by: innie trace list/show/stats, API
            │   │                       Contains: trace_sessions, trace_spans
            │   │
            │   └── YYYY-MM-DD.jsonl    Created by: PostToolUse hook (append, <1ms)
            │                           Format: {ts, tool} — fast-path only
            │
            ├── .index/
            │   └── memory.db           Created by: innie index
            │                           Written by: search.index_files()
            │                           Read by: search.search_hybrid/keyword/semantic()
            │                           Contains: chunks, file_index, chunk_fts, chunk_embeddings
            │
            └── heartbeat-state.json    Created by: heartbeat Phase 3
                                        Read by: heartbeat Phase 1 (cutoff timestamp)
                                        Content: {last_run, processed_session_ids, last_git_sha}
```

---

## Data Ownership Matrix

| File / Directory | Owner | Backup needed | Rebuilable? |
|---|---|---|---|
| `SOUL.md` | User | Yes | No — manually written |
| `CONTEXT.md` | innie (heartbeat) | Yes | Partially — rebuilt from decay + heartbeat |
| `profile.yaml` | innie + user | Yes | Yes — via `innie create` |
| `data/**` | innie + user | **Yes** | No — primary knowledge base |
| `state/sessions/` | innie (hooks) | Optional | No (source data for heartbeat) |
| `state/trace/traces.db` | innie (hooks + handle) | Optional | No (session + span history) |
| `state/trace/*.jsonl` | innie (PostToolUse) | No | No (fast-path log) |
| `state/.index/memory.db` | innie (indexer) | No | **Yes** — `innie index` rebuilds |
| `state/heartbeat-state.json` | innie (heartbeat) | No | Yes — reset to epoch 0 |
| `hooks/` bash shims | innie (backend install) | No | Yes — `innie backend install` |
| `config.toml` | User | Yes | Yes — `innie init` regenerates |

---

## Search Index Data Model

```
memory.db
│
├── file_index                          Track indexed files
│   ├── file_path (PK)
│   ├── mtime                           Last modified time (float)
│   ├── chunk_count
│   └── indexed_at
│
├── chunks                              Text chunk storage
│   ├── id (PK AUTOINCREMENT)
│   ├── file_path
│   ├── chunk_idx                       Position within file
│   ├── content                         ~100 words
│   ├── mtime
│   └── indexed_at
│
├── chunk_fts (VIRTUAL — FTS5)          Keyword search
│   ├── content
│   └── content_rowid → chunks.id
│
└── chunk_embeddings (VIRTUAL — vec0)  Vector similarity
    ├── chunk_id → chunks.id
    └── embedding float[768]            bge-base-en vectors
```
