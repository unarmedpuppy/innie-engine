"""Channel policy — allowlist/open/deny rules for DMs and group chats."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def is_allowed(
    channel_config: dict[str, Any],
    contact_id: str,
    is_group: bool,
    text: str,
    agent_name: str,
) -> bool:
    """Return True if this message should be processed by the agent.

    Args:
        channel_config: The channel's config dict (e.g. channels.yaml bluebubbles section).
        contact_id: Sender phone/email (BB) or Mattermost user_id.
        is_group: Whether this is a group chat.
        text: Message text (used for mention check).
        agent_name: Agent name for mention matching (e.g. "Avery").
    """
    if is_group:
        policy = channel_config.get("group_policy", "deny")
        allow_from = channel_config.get("group_allow_from", [])
        require_mention = channel_config.get("require_mention", True)
    else:
        policy = channel_config.get("dm_policy", "deny")
        allow_from = channel_config.get("allow_from", [])
        require_mention = False  # DMs never require mention

    if policy == "deny":
        return False
    elif policy == "allowlist":
        if "*" not in allow_from and contact_id not in allow_from:
            logger.debug(f"[policy] blocked {contact_id} — not in allowlist")
            return False
    elif policy == "open":
        pass
    else:
        logger.warning(f"[policy] unknown policy '{policy}', defaulting to deny")
        return False

    # Group mention gating
    if is_group and require_mention:
        if agent_name.lower() not in text.lower():
            logger.debug(f"[policy] group message skipped — no mention of {agent_name}")
            return False

    return True
