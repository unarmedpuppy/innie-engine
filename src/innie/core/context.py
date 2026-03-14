"""Context assembly + XML-tag injection for session-start hooks.

Assembles identity, working memory, semantic search results, and session
metadata into XML-tagged blocks that get injected into the AI backend's
system prompt via stdout.
"""

from datetime import datetime
from pathlib import Path

from innie.core import paths
from innie.core.profile import load_profile


def _read_optional(path: Path) -> str | None:
    if path.exists():
        content = path.read_text().strip()
        return content if content else None
    return None


def _budget_chars(tokens: int) -> int:
    return tokens * 4  # ~4 chars per token


def build_session_context(
    agent_name: str | None = None,
    cwd: str | None = None,
) -> str:
    """Build full context for session-start injection.

    Returns XML-tagged string to be printed to stdout by the hook shim.
    """
    profile = load_profile(agent_name)
    from innie.core.config import get

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
            from innie.core.search import search_for_context

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
        '- Search: `innie search "query"`',
    ]
    if cwd:
        status_lines.append(f"- Working dir: {cwd}")
    status_lines.append("</session-status>")
    parts.append("\n".join(status_lines))

    # 6. Memory tools reference — fixed budget, not squeezed
    load_hint = (
        '  innie context load PATH                           # read full file from data/ (index-only mode active)\n'
        if index_only else ""
    )
    parts.append(
        "<memory-tools>\n"
        "Live knowledge base ops (call anytime — no need to wait for heartbeat):\n"
        '  innie search "query"                              # search knowledge base\n'
        '  innie ls [path]                                   # browse data/ directory\n'
        + load_hint +
        '  innie memory store learning "Title" "Content"     # store a learning\n'
        "    --category debugging|patterns|tools|infrastructure|processes\n"
        "    --confidence high|medium|low\n"
        '  innie memory store decision "Title" "Content"     # store a decision\n'
        "    --project PROJECT\n"
        '  innie memory store project "Name" "Progress"      # update project context\n'
        '  innie memory forget PATH "Why it\'s wrong"         # supersede (PATH relative to data/)\n'
        '  innie context add "- Open item text"              # add open item (next session)\n'
        '  innie context remove "text"                       # remove open item (next session)\n'
        "  innie context compress                            # LLM dedup of open items\n"
        "</memory-tools>"
    )

    return "\n\n".join(parts)


def build_precompact_warning(agent_name: str | None = None) -> str:
    """Build the pre-compact memory flush warning."""
    name = agent_name or paths.active_agent()
    ctx_path = paths.context_file(name)
    return f"""<system-reminder priority="critical">
CONTEXT COMPACTION IMMINENT — Flush your working memory NOW before it is lost.

Run these in order:
1. `innie memory store learning "Title" "Content"` — for any non-obvious discoveries made this session
2. `innie memory store decision "Title" "Content" --project NAME` — for any arch choices made
3. `innie memory forget PATH "reason"` — for anything you now know is wrong
4. `innie context add "- item"` — for new open items not yet in CONTEXT.md
5. `innie context remove "text"` — for anything now resolved
6. Update {ctx_path} directly for any focus shift or critical state

Keep CONTEXT.md under 200 lines. Prune stale entries.
Confirm when done.
</system-reminder>"""
