"""Resolve a .torrent file URL to its real title.

Calls the backend ``/api/resolve_torrent`` endpoint, which downloads
the .torrent file (size- and time-bounded) and parses its metadata
with libtorrent.  Mirrors ``resolve_magnet``'s output so the assistant
can feed the result into the same downstream pipeline (library
duplicate check → user confirmation → create_download).
"""

from openlist_ani.assistant.builtin_skills.support.oani_backend_client import (
    BackendClient,
)
from openlist_ani.adapters.configuration import config


async def run(
    url: str = "",
    **kwargs,
) -> str:
    """Resolve a .torrent file URL to its real title.

    Args:
        url: ``http(s)://`` URL pointing at a .torrent file (required).
    """
    if not url:
        return (
            "Error: 'url' parameter is required (http(s):// link to a .torrent file)."
        )

    client = BackendClient(config.backend_url)
    try:
        data = await client.resolve_torrent(url)
    except Exception as e:
        return f"Error resolving torrent file: {e}"
    finally:
        await client.close()

    success = data.get("success", False)
    title = data.get("title")
    source = data.get("source") or "?"
    file_count = data.get("file_count")
    msg = data.get("message", "")

    if not success:
        return (
            f"Failed to resolve torrent file: {msg}\n"
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
        "confirmation, then run create_download.py with the torrent URL and title. "
        "Pass the title verbatim — it is used by the backend to rename "
        "the file. Do NOT modify or fabricate it.",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    from openlist_ani.assistant.builtin_skills.runtime.cli import run_cli

    run_cli(run)
