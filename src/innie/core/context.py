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
    remaining = budget - used
    if remaining > 200 and cwd:
        try:
            from innie.core.search import search_for_context

            results = search_for_context(cwd, agent_name, max_chars=remaining)
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

    return "\n\n".join(parts)


def build_precompact_warning(agent_name: str | None = None) -> str:
    """Build the pre-compact memory flush warning."""
    name = agent_name or paths.active_agent()
    ctx_path = paths.context_file(name)
    return f"""<system-reminder priority="critical">
CONTEXT COMPACTION IMMINENT — Save your working memory NOW.

Before this context is compressed, you MUST update {ctx_path} with:
1. What you were working on (current focus)
2. Key decisions made this session
3. Any open items or blockers
4. Important context that would be lost

Keep CONTEXT.md under 200 lines. Prune stale entries.
Confirm when saved.
</system-reminder>"""
