"""Resolve a magnet link to its real title.

Calls the backend ``/api/resolve_magnet`` endpoint.  The backend tries
the magnet's ``dn=`` parameter first, then falls back to libtorrent
metadata (DHT/peers, time-bounded).  Collection filtering is handled
outside the resolver.
"""

from openlist_ani.assistant.builtin_skills.support.oani_backend_client import (
    BackendClient,
)
from openlist_ani.adapters.configuration import config


async def run(
    magnet: str = "",
    metadata_timeout: int = 30,
    **kwargs,
) -> str:
    """Resolve a magnet to its real title.

    Args:
        magnet: Magnet URI (required).
        metadata_timeout: Budget in seconds for the libtorrent metadata
            fetch.  Ignored when the magnet's ``dn=`` parameter is
            already usable.  Defaults to 30.
    """
    if not magnet:
        return "Error: 'magnet' parameter is required."

    client = BackendClient(config.backend_url)
    try:
        data = await client.resolve_magnet(magnet, metadata_timeout=metadata_timeout)
    except Exception as e:
        return f"Error resolving magnet: {e}"
    finally:
        await client.close()

    success = data.get("success", False)
    title = data.get("title")
    source = data.get("source") or "?"
    file_count = data.get("file_count")
    msg = data.get("message", "")

    if not success:
        return (
            f"Failed to resolve magnet: {msg}\n"
            "Ask the user for the resource title — do NOT fabricate one."
        )

    lines = [
        f"Title: {title}",
        f"Source: {source}",
    ]
    if file_count is not None:
        lines.append(f"Files: {file_count}")

    lines += [
        "",
        "Next: check the library with query_library.py, ask for explicit "
        "confirmation, then run create_download.py with the magnet and title. "
        "Pass the title verbatim — it is used by the backend to rename "
        "the file. Do NOT modify or fabricate it.",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    from openlist_ani.assistant.builtin_skills.runtime.cli import run_cli

    run_cli(run)
