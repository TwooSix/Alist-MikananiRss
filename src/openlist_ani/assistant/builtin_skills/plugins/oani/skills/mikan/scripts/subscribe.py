"""Subscribe to a bangumi on Mikan for RSS updates."""

from openlist_ani.assistant.builtin_skills.support.mikan_client import MikanClient
from openlist_ani.assistant.builtin_skills.runtime.confirmation import (
    confirmation_error,
)
from openlist_ani.adapters.configuration import config


async def run(
    bangumi_id: str = "",
    subtitle_group_id: str = "",
    language: str = "",
    confirmed: bool = False,
    **kwargs,
) -> str:
    """Subscribe to a bangumi on Mikan.

    Args:
        bangumi_id: Mikan bangumi ID (required).
        subtitle_group_id: Optional subtitle group ID to subscribe to a specific fansub.
        language: Optional language filter. 0=all, 1=Simplified Chinese, 2=Traditional Chinese.
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
        lang = int(language) if language else None

        success = await client.subscribe_bangumi(
            bangumi_id=int(bangumi_id),
            subtitle_group_id=sg_id,
            language=lang,
        )
    except Exception as e:
        return f"Error subscribing: {e}"
    finally:
        await client.close()

    if success:
        detail = f"bangumi_id={bangumi_id}"
        if subtitle_group_id:
            detail += f", subtitle_group={subtitle_group_id}"
        if language:
            lang_names = {0: "all", 1: "Simplified Chinese", 2: "Traditional Chinese"}
            detail += f", language={lang_names.get(int(language), language)}"
        return f"Successfully subscribed to Mikan bangumi ({detail})."
    else:
        return f"Failed to subscribe to bangumi {bangumi_id}. Check credentials and bangumi ID."


if __name__ == "__main__":
    from openlist_ani.assistant.builtin_skills.runtime.cli import run_cli

    run_cli(run)
