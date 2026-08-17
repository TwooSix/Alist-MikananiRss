"""Add a new RSS feed URL for monitoring."""

from openlist_ani.assistant.builtin_skills.support.oani_backend_client import (
    BackendClient,
)
from openlist_ani.assistant.builtin_skills.runtime.confirmation import (
    confirmation_error,
)
from openlist_ani.adapters.configuration import config


async def run(
    url: str = "",
    confirmed: bool = False,
    **kwargs,
) -> str:
    """Add an RSS feed URL to the monitoring list.

    Args:
        url: RSS feed URL to add (required).
    """
    if error := confirmation_error(confirmed):
        return error
    if not url:
        return "Error: 'url' parameter is required (RSS feed URL)."

    client = BackendClient(config.backend_url)
    try:
        data = await client.add_rss_url(url)
    except Exception as e:
        return f"Error adding RSS URL: {e}"
    finally:
        await client.close()

    success = data.get("success", False)
    msg = data.get("message", "")
    urls = data.get("urls", [])

    if success:
        return (
            f"RSS URL added successfully.\n{msg}\nCurrent feeds ({len(urls)}):\n"
            + "\n".join(f"  - {u}" for u in urls)
        )
    else:
        return f"Failed to add RSS URL: {msg}"


if __name__ == "__main__":
    from openlist_ani.assistant.builtin_skills.runtime.cli import run_cli

    run_cli(run)
