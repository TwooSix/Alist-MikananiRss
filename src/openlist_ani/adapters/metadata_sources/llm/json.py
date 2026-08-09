"""Utility functions for parser tools."""


def _json_fence_payload(text: str) -> str | None:
    marker = "```json"
    payload_start = text.find(marker)
    if payload_start < 0:
        return None
    payload_start += len(marker)
    payload_end = text.find("```", payload_start)
    if payload_end < 0:
        return None
    return text[payload_start:payload_end].strip()


def parse_json_from_markdown(text: str) -> str | None:
    """Extract JSON string from markdown code block or plain text.

    Args:
        text: Text containing JSON, possibly in markdown code blocks

    Returns:
        Extracted JSON string or None if not found
    """
    if fenced := _json_fence_payload(text):
        return fenced

    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return text[start:end]
    except ValueError:
        return None


def parse_json_array_from_markdown(text: str) -> str | None:
    """Extract JSON array string from markdown code block or plain text.

    Looks for a JSON array (starting with '[') in markdown code blocks or raw text.

    Args:
        text: Text containing JSON array, possibly in markdown code blocks

    Returns:
        Extracted JSON array string or None if not found
    """
    if (fenced := _json_fence_payload(text)) and fenced.startswith("["):
        return fenced

    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        return text[start:end]
    except ValueError:
        return None
