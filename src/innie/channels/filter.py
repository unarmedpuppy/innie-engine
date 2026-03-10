"""Strip internal artifacts from Claude output before sending to channels."""

import re

# XML blocks injected into system context — never sent to end users
_XML_BLOCKS = re.compile(
    r"<(?:agent-identity|agent-context|session-status|memory-context|memory-tools)"
    r">.*?</[a-z-]+>",
    re.DOTALL,
)
_TOOL_ERROR = re.compile(r"<tool_error>.*?</tool_error>", re.DOTALL)
_EXCESS_NEWLINES = re.compile(r"\n{3,}")


def filter_for_channel(text: str) -> str:
    """Remove internal blocks, tool errors, and excess whitespace."""
    text = _TOOL_ERROR.sub("", text)
    text = _XML_BLOCKS.sub("", text)
    text = _EXCESS_NEWLINES.sub("\n\n", text)
    return text.strip()
