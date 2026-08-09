"""Unsubscribe from a bangumi on Mikan."""

from openlist_ani.assistant.builtin_skills.support.mikan_client import MikanClient
from openlist_ani.assistant.builtin_skills.runtime.confirmation import (
    confirmation_error,
)
from openlist_ani.adapters.configuration import config


async def run(
    bangumi_id: str = "",
    subtitle_group_id: str = "",
    confirmed: bool = False,
    **kwargs,
) -> str:
    """Unsubscribe from a bangumi on Mikan.

    Args:
        bangumi_id: Mikan bangumi ID (required).
        subtitle_group_id: Optional subtitle group ID. Empty = unsubscribe from all groups.
    """
    if error := confirmation_error(confirmed):
        return error
    if not bangumi_id:
        return "Error: 'bangumi_id' parameter is required."

    mikan = config.mikan
    if not mikan.username or not mikan.password:
        return "Error: Mikan credentials not configured. Set [mikan] username and password in config.toml."

    client = MikanClient(username=mikan.username, password=mikan.password)
    try:
        sg_id = int(subtitle_group_id) if subtitle_group_id else None
        success = await client.unsubscribe_bangumi(
            bangumi_id=int(bangumi_id),
            subtitle_group_id=sg_id,
        )
    except Exception as e:
        return f"Error unsubscribing: {e}"
    finally:
        await client.close()

    if success:
        detail = f"bangumi_id={bangumi_id}"
        if subtitle_group_id:
            detail += f", subtitle_group={subtitle_group_id}"
        return f"Successfully unsubscribed from Mikan bangumi ({detail})."
    else:
        return f"Failed to unsubscribe from bangumi {bangumi_id}."


if __name__ == "__main__":
    from openlist_ani.assistant.builtin_skills.runtime.cli import run_cli

    run_cli(run)
