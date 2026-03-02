# ADR-0011 — Secret Scanning Before Indexing

**Status:** Accepted
**Date:** 2026-02
**Context:** Preventing accidental indexing of sensitive credentials

---

## Context

The knowledge base is a collection of markdown files — session notes, learnings, meeting notes. Some of these files might inadvertently contain secrets: API keys copied from a config, tokens pasted from a browser, AWS credentials from a `.env` file that got included.

If secrets make it into the search index:
- They could be surfaced in search results and injected into AI context
- They could be committed to a git remote (if auto-commit is enabled)
- They could be exposed via the fleet gateway's memory API

We need to prevent secrets from entering the index.

---

## Decision

**Regex-based secret scanning integrated into `collect_files()`.**

Before any file is indexed, `should_index_file(path)` is called. It returns `False` if:
1. The filename matches the skip list (`.env`, `credentials.json`, etc.)
2. The file extension is binary (`.db`, `.pkl`, `.pem`, `.key`, etc.)
3. The file content matches any of 10 secret regex patterns

Files that return `False` are never read by the embedding service and never stored in `chunk_fts` or `chunk_embeddings`.

**Detected patterns:**
- OpenAI API key: `sk-[proj-]?[A-Za-z0-9]{20,}`
- Anthropic API key: `sk-ant-[A-Za-z0-9\-]{40,}`
- AWS Access Key: `AKIA[0-9A-Z]{16}`
- GitHub token: `ghp_[A-Za-z0-9]{36}`
- Slack token: `xox[baprs]-[A-Za-z0-9\-]{10,}`
- Bearer token: `Bearer [A-Za-z0-9\-._~+\/]{20,}`
- Private key header: `-----BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY-----`
- High-entropy strings in key/secret/token fields

---

## Rationale

**Why at index time, not at write time?** Files might be created by migration (importing from another system), by the AI assistant directly, or by tools we don't control. We can't guarantee all write paths run secret scanning. The index is the correct chokepoint — everything must pass through indexing to appear in search results.

**Why regex, not entropy analysis?** Entropy analysis (detecting high-entropy strings that look like secrets) has a high false positive rate on base64 content, UUIDs, and hash values common in code. Targeted regex patterns match known secret formats with much lower false positive rates.

**Why skip the whole file rather than redacting?** Redacting at chunk level is complex and error-prone. If a file contains a secret, it's likely the whole file is sensitive (e.g., a config dump). Skipping the file entirely is the conservative, safe choice.

**Why not block at git commit time?** We don't control the git commit workflow. Users might commit manually. The index is the right layer — it's always under innie's control.

---

## Consequences

**Positive:**
- Secrets never enter the search index
- Secrets never get injected into AI context via search results
- Secrets never get committed to git via auto-commit (files excluded from index are also excluded from awareness)
- Protects against API key leakage even if the user accidentally pastes one into session notes

**Negative:**
- False positives: a file that looks like it contains a secret but doesn't will be excluded from indexing. The user won't know unless they run `innie doctor`.
- The regex patterns need updating as new secret formats emerge

**Neutral:**
- Scanning runs on every call to `collect_files()` — once per indexing run. Cost is proportional to file count and content size, but is cheap relative to embedding generation.
- The skip list covers the most common accidentally-included files (`.env`). This is not a complete solution — users should not store secrets in markdown files at all.
