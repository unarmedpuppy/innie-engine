"""Context assembly, compression utilities, and XML-tag injection for session-start hooks.

Assembles identity, working memory, semantic search results, and session
metadata into XML-tagged blocks that get injected into the AI backend's
system prompt via stdout.
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from grove.core import paths
from grove.core.profile import load_profile


def _read_optional(path: Path) -> str | None:
    if path.exists():
        content = path.read_text().strip()
        return content if content else None
    return None


def _budget_chars(tokens: int) -> int:
    return tokens * 4  # ~4 chars per token


def _detect_project(cwd: str | None) -> str | None:
    """Detect the active project from the current working directory."""
    if not cwd:
        return None
    workspace = Path.home() / "workspace"
    try:
        rel = Path(cwd).relative_to(workspace)
        return rel.parts[0] if rel.parts else None
    except ValueError:
        return None


def build_session_context(
    agent_name: str | None = None,
    cwd: str | None = None,
) -> str:
    """Build full context for session-start injection.

    Returns XML-tagged string to be printed to stdout by the hook shim.
    """
    profile = load_profile(agent_name)
    from grove.core.config import get

    max_tokens = get("context.max_tokens", 2000)
    budget = _budget_chars(max_tokens)
    parts: list[str] = []
    used = 0

    # 1. Identity (SOUL.md) — 15% budget
    soul_budget = int(budget * 0.15)
    if profile.soul:
        soul = profile.soul[:soul_budget]
        parts.append(f"<agent-identity>\n{soul}\n</agent-identity>")
        used += len(soul)

    # 2. User profile (user.md) — from global
    user_content = _read_optional(paths.user_file())
    if user_content:
        user_budget = int(budget * 0.15)
        user = user_content[:user_budget]
        parts.append(f"<user-profile>\n{user}\n</user-profile>")
        used += len(user)

    # 3. Working memory (CONTEXT.md) — 35% budget
    ctx_budget = int(budget * 0.35)
    if profile.context:
        ctx = profile.context[:ctx_budget]
        parts.append(f'<agent-context agent="{profile.name}">\n{ctx}\n</agent-context>')
        used += len(ctx)

    # 3b. Project walnut — now.md + tasks.md for active project
    project = _detect_project(cwd)
    if project:
        now_content = _read_optional(paths.project_now(project, agent_name))
        tasks_content = _read_optional(paths.project_tasks(project, agent_name))
        walnut_parts = []
        if now_content:
            walnut_parts.append(f"**now.md**\n{now_content}")
        if tasks_content:
            walnut_parts.append(f"**tasks.md**\n{tasks_content}")
        if walnut_parts:
            walnut_budget = int(budget * 0.20)
            walnut_text = "\n\n".join(walnut_parts)[:walnut_budget]
            parts.append(f'<project-context project="{project}">\n{walnut_text}\n</project-context>')
            used += len(walnut_text)

    # 4. Semantic search results — remaining budget
    # Switch to index-only mode when knowledge base exceeds threshold (saves tokens)
    index_threshold = get("context.index_threshold", 200)
    index_only = False
    try:
        data_dir = paths.data_dir(agent_name)
        if data_dir.exists():
            file_count = sum(1 for _ in data_dir.rglob("*.md"))
            index_only = file_count > index_threshold
    except Exception:
        pass

    remaining = budget - used
    if remaining > 200 and cwd:
        try:
            from grove.core.search import search_for_context

            results = search_for_context(cwd, agent_name, max_chars=remaining, index_only=index_only)
            if results:
                parts.append(f"<memory-context>\n{results}\n</memory-context>")
        except Exception:
            pass  # Graceful degradation if index unavailable

    # 5. Session status metadata
    now = datetime.now()
    tz = now.astimezone().tzname()
    status_lines = [
        f'<session-status agent="{profile.name}" date="{now.strftime("%Y-%m-%d")}">',
        f"- Agent: {profile.name} ({profile.role})",
        f"- Time: {now.strftime('%Y-%m-%d %H:%M')} {tz}",
        f"- Knowledge base: {paths.data_dir(profile.name)}",
        '- Search: `g search "query"`',
    ]
    if cwd:
        status_lines.append(f"- Working dir: {cwd}")
    status_lines.append("</session-status>")
    parts.append("\n".join(status_lines))

    # 6. Memory tools reference — fixed budget, not squeezed
    load_hint = (
        '  g context load PATH                           # read full file from data/ (index-only mode active)\n'
        if index_only else ""
    )

    # Load topic catalog for discovery signal
    catalog_lines = ""
    try:
        from grove.core.catalog import format_catalog_for_context, load_topic_catalog
        catalog = load_topic_catalog(agent_name)
        if catalog:
            catalog_lines = format_catalog_for_context(catalog) + "\n"
    except Exception:
        pass

    parts.append(
        "<memory-tools>\n"
        "Live knowledge base ops (call anytime — no need to wait for heartbeat):\n"
        '  g search "query"                              # search knowledge base\n'
        '  g ls [path]                                   # browse data/ directory\n'
        + load_hint +
        '  g memory store learning "Title" "Content"     # store a learning\n'
        "    --category debugging|patterns|tools|infrastructure|processes\n"
        "    --confidence high|medium|low\n"
        '  g memory store decision "Title" "Content"     # store a decision\n'
        "    --project PROJECT\n"
        '  g memory store project "Name" "Progress"      # update project context\n'
        '  g memory forget PATH "Why it\'s wrong"         # supersede (PATH relative to data/)\n'
        '  g context add "- Open item text"              # add open item (next session)\n'
        '  g context remove "text"                       # remove open item (next session)\n'
        "  g context compress                            # LLM dedup of open items\n"
        + catalog_lines
        + "</memory-tools>"
    )

    return "\n\n".join(parts)


def build_precompact_warning(agent_name: str | None = None) -> str:
    """Build the pre-compact memory flush warning."""
    import os
    name = agent_name or paths.active_agent()
    ctx_path = paths.context_file(name)
    project = _detect_project(os.getcwd())
    project_step = (
        f'\n0. `g project log {project} "<one-line summary of what happened this session>"` — spine entry before compaction\n'
        if project else ""
    )
    return f"""<system-reminder priority="critical">
CONTEXT COMPACTION IMMINENT — Flush your working memory NOW before it is lost.

Run these in order:{project_step}
1. `g memory store learning "Title" "Content"` — for any non-obvious discoveries made this session
2. `g memory store decision "Title" "Content" --project NAME` — for any arch choices made
3. `g memory forget PATH "reason"` — for anything you now know is wrong
4. `g context add "- item"` — for new open items not yet in CONTEXT.md
5. `g context remove "text"` — for anything now resolved
6. Update {ctx_path} directly for any focus shift or critical state

Keep CONTEXT.md under 200 lines. Prune stale entries.
Confirm when done.
</system-reminder>"""


# ── Context compression ───────────────────────────────────────────────────────

_WORDS_PER_TOKEN = 1.3


def estimate_tokens(text: str) -> int:
    """Rough token estimate via word count. Conservative (overshoots slightly)."""
    return int(len(text.split()) * _WORDS_PER_TOKEN)


def compress_context_open_items(
    ctx_file: Path,
    agent: Optional[str] = None,
    recent_context: Optional[str] = None,
) -> tuple[int, int]:
    """LLM-compress the Open Items section of a CONTEXT.md file.

    Calls the configured heartbeat LLM provider to deduplicate and trim open items.
    Writes the result in-place. Appends to memory-ops.jsonl.

    Args:
        ctx_file: Path to CONTEXT.md
        agent: Agent name override
        recent_context: Optional summary of recently active topics/projects. When
            provided, the LLM is instructed not to remove items related to these
            active areas (freshness lock — prevents post-compaction amnesia).

    Returns:
        (before_count, after_count) — bullet counts before and after.
        Returns (0, 0) if the section is empty, too small, or the LLM call fails.
        Never raises.
    """
    try:
        from grove.core.config import get
        from grove.heartbeat.extract import (
            _call_anthropic,
            _call_openai_compatible,
            _resolve_openclaw,
        )

        content = ctx_file.read_text(encoding="utf-8")

        marker = "## Open Items"
        if marker not in content:
            return (0, 0)

        start = content.index(marker)
        after_header = content.index("\n", start) + 1
        next_section = re.search(r"^##\s", content[after_header:], re.MULTILINE)
        end = after_header + next_section.start() if next_section else len(content)

        open_items_block = content[after_header:end].strip()
        if not open_items_block:
            return (0, 0)

        bullets = [line for line in open_items_block.splitlines() if line.strip().startswith("-")]
        if len(bullets) <= 3:
            return (0, 0)

        freshness_clause = ""
        if recent_context and recent_context.strip():
            freshness_clause = (
                f"\nActive right now (DO NOT remove open items related to these):\n"
                f"{recent_context.strip()}\n"
            )

        prompt = f"""You are compressing the Open Items section of an AI agent's working memory.

Current open items:
{open_items_block}
{freshness_clause}
Rules:
- Remove items that are clearly resolved, superseded, or irrelevant
- Merge near-duplicate items into one
- Keep items that are genuinely open and non-obvious
- NEVER remove items related to currently active topics listed above
- Preserve the exact bullet format: "- item text"
- Return ONLY the compressed bullet list, no explanation, no headers

Output the compressed list:"""

        provider = get("heartbeat.provider", "auto")
        external_url = get("heartbeat.external_url", "")
        model = get("heartbeat.model", "auto")

        if provider == "auto":
            if (Path.home() / ".openclaw" / "openclaw.json").exists():
                provider = "openclaw"
            elif external_url:
                provider = "external"
            else:
                provider = "anthropic"

        if provider == "openclaw":
            url, key, m = _resolve_openclaw()
            compressed = _call_openai_compatible(prompt, m, url, api_key=key)
        elif provider == "external":
            import os
            key = (get("heartbeat.external_api_key", "")
                   or os.environ.get("INNIE_HEARTBEAT_API_KEY", "")
                   or os.environ.get("ANTHROPIC_API_KEY", ""))
            compressed = _call_openai_compatible(
                prompt,
                model if model != "auto" else "default",
                external_url,
                api_key=key,
            )
        else:
            compressed = _call_anthropic(prompt, "claude-haiku-4-5-20251001")

        compressed = compressed.strip()
        new_bullets = [line for line in compressed.splitlines() if line.strip().startswith("-")]
        if not new_bullets:
            return (0, 0)

        new_content = (
            content[:after_header]
            + "\n"
            + compressed
            + "\n\n"
            + content[end:].lstrip("\n")
        )
        new_content = re.sub(
            r"\*Last updated:.*?\*",
            f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
            new_content,
        )
        ctx_file.write_text(new_content, encoding="utf-8")

        # Audit trail
        ops_file = paths.memory_ops_file(agent)
        ops_file.parent.mkdir(parents=True, exist_ok=True)
        with open(ops_file, "a") as f:
            f.write(json.dumps({
                "ts": int(time.time()),
                "op": "context_compress",
                "source": "heartbeat",
                "removed": len(bullets) - len(new_bullets),
                "kept": len(new_bullets),
            }, separators=(",", ":")) + "\n")

        return (len(bullets), len(new_bullets))

    except Exception:
        return (0, 0)
