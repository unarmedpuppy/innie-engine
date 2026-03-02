# Security Model

innie is a local-first tool that touches your filesystem, your AI assistant configuration, and optionally your git history. This page documents the security boundaries and the measures in place.

---

## What innie Accesses

| Resource | Access type | When |
|---|---|---|
| `~/.innie/` | Read + Write | Always |
| `~/.claude/settings.json` | Read + Write (namespace-safe merge) | `innie backend install` only |
| `~/.cursor/` config | Read + Write (namespace-safe merge) | `innie backend install` only |
| `~/.zshrc` / `~/.bashrc` | Append only | `innie alias` only (opt-in) |
| git repos (read) | `git log`, `git diff` | Heartbeat collect phase |
| git repos (write) | `git add + commit + push` | Heartbeat route phase (opt-in, config) |
| External embedding API | HTTP POST | Search indexing (if external provider configured) |
| Network (fleet) | HTTP server | `innie serve` and `innie fleet start` only |

---

## Secret Scanning

**File:** `src/innie/core/secrets.py`

Before any file is indexed, it is scanned for secrets using regex patterns. Files containing matches are excluded from the search index entirely.

### Detected Patterns

| Pattern | Regex target |
|---|---|
| OpenAI API key | `sk-[A-Za-z0-9]{20,}` |
| Anthropic API key | `sk-ant-[A-Za-z0-9\-]{40,}` |
| AWS Access Key | `AKIA[0-9A-Z]{16}` |
| AWS Secret Key | High-entropy 40-char string near `aws_secret` |
| GitHub token | `ghp_[A-Za-z0-9]{36}` |
| Slack token | `xox[baprs]-[A-Za-z0-9\-]{10,}` |
| Bearer token | `Bearer [A-Za-z0-9\-._~+\/]{20,}` |
| Private key header | `-----BEGIN (RSA\|EC\|OPENSSH\|PRIVATE) KEY-----` |
| Generic high-entropy | Long random-looking strings in `*_key`, `*_secret`, `*_token` fields |

### Skip List

These files are never indexed regardless of content:

- `.env`, `.env.*`
- `credentials.json`, `secrets.json`, `*.pem`, `*.key`
- Binary extensions: `.db`, `.pkl`, `.bin`, `.so`, `.dylib`

### `should_index_file(path)` Contract

```python
def should_index_file(path: Path) -> bool:
    # Returns False if:
    # 1. Filename matches skip list
    # 2. Extension is binary
    # 3. File contains secret pattern matches
    # Returns True otherwise
```

This function is called on every file before indexing. A file that returns False is never read by the embedding service and never stored in the search index.

---

## Destructive Command Guard (dcg)

**File:** `src/innie/hooks/dcg-guard.sh`

A PreToolUse hook that intercepts tool calls before the AI assistant executes them. If the command matches a dangerous pattern, it is blocked with an error message.

### Default Blocked Patterns

| Category | Examples |
|---|---|
| Filesystem destruction | `rm -rf /`, `rm -rf ~`, `rm -rf *` |
| Database destruction | `DROP TABLE`, `DROP DATABASE`, `TRUNCATE TABLE` |
| Git force operations | `git push --force`, `git reset --hard`, `git clean -fdx` |
| System damage | `mkfs`, `dd if=`, `:(){ :|:& };:` (fork bomb) |
| Credential exposure | `chmod 777`, `curl \| bash`, `wget \| sh` |

### Fail-Open Design

If the guard script errors (crashes, timeout, etc.), the command **proceeds** — the guard never blocks the AI assistant from working. This is deliberate: a false positive that blocks legitimate work is worse than missing a rare destructive command.

### Configuration

```yaml
# profile.yaml
guard:
  enabled: true
  extra_patterns:
    - "kubectl delete namespace"
    - "terraform destroy"
```

See [ADR-0020](../adrs/0020-dcg-guard.md) for rationale.

---

## Hook Installation Safety

The Claude Code backend uses a **namespace-safe merge** for hook installation:

1. Read existing `settings.json`
2. Find `hooks` section (or create it)
3. For each hook event (SessionStart, Stop, etc.):
   - If the event key doesn't exist, create it
   - If it exists, **append** to the list (never replace)
   - Each hook entry is tagged with the innie shim path for identification
4. Write back

Uninstallation removes only entries where the command path starts with `~/.innie/hooks/`. It cannot accidentally remove user-configured hooks.

---

## Network Surface

By default, innie is entirely local with no network access.

Network is only active when:

| Service | Command | Default port | Bound to |
|---|---|---|---|
| Jobs API | `innie serve` | 8013 | `0.0.0.0` — **change if public** |
| Fleet gateway | `innie fleet start` | 8020 | `0.0.0.0` — **change if public** |
| Embedding service | `docker compose up` | 8766 | `localhost` only |

**Production recommendation:** Run behind a reverse proxy (e.g., Traefik) with:
- TLS termination
- IP allowlist (LAN + Tailscale only)
- Basic auth for public exposure

The serve and fleet apps include CORS middleware with `allow_origins=["*"]`. Restrict this if exposing beyond localhost.

---

## Git Safety

When `git.auto_commit = true`, innie runs git commands in the `data/` directory only. It never modifies git repos in your working directory.

The commit runs:
```bash
git -C ~/.innie/agents/<name>/data add -A
git -C ~/.innie/agents/<name>/data commit -m "heartbeat: YYYY-MM-DD HH:MM"
```

If `git.auto_push = true`, it also runs `git push`. This requires a remote to be configured and appropriate credentials. innie does not manage git credentials.

---

## Isolation Guarantees

| Guarantee | How |
|---|---|
| Knowledge bases don't cross-contaminate | Each agent has a completely separate directory tree |
| Test runs don't touch real data | `INNIE_HOME` env var overrides location; tests always set it |
| Uninstall is clean | `innie backend uninstall` removes only tagged hooks; no orphans |
| No ambient state | Config is file-based TOML; no system-level services installed by default |
