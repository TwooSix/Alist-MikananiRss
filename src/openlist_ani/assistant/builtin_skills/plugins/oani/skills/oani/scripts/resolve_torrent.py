"""Resolve a .torrent file URL to its real title.

Calls the backend ``/api/resolve_torrent`` endpoint, which downloads
the .torrent file (size- and time-bounded) and parses its metadata
with libtorrent.  Mirrors ``resolve_magnet``'s output so the assistant
can feed the result into the same downstream pipeline (library
duplicate check → user confirmation → create_download).
"""

from pathlib import PurePosixPath

from openlist_ani.application.collection import VIDEO_EXTENSIONS
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
    files = data.get("files") or []
    video_count = sum(
        PurePosixPath(str(item.get("name") or "")).suffix.lower() in VIDEO_EXTENSIONS
        for item in files
        if isinstance(item, dict)
    )
    collection_hint = video_count > 1
    msg = data.get("message", "")
    error_code = data.get("error_code")

    if not success:
        if error_code == "invalid_torrent_url":
            guidance = (
                "Ask the user for a valid HTTP(S) .torrent URL. A title cannot "
                "repair an invalid URL."
            )
        elif error_code == "torrent_download_failed":
            guidance = (
                "Ask for a reachable .torrent URL or an attached torrent source. "
                "A title cannot repair the failed download."
            )
        elif error_code == "libtorrent_unavailable":
            guidance = (
                "This is a backend dependency problem. Report it and do not ask "
                "the user for a title as a workaround."
            )
        elif error_code == "torrent_parse_failed":
            guidance = (
                "Ask for a valid .torrent file or magnet link. Supplying a title "
                "does not make an invalid torrent parseable."
            )
        else:
            guidance = "Report the resolver error as-is; do NOT fabricate a title."
        return f"Failed to resolve torrent file: {msg}\n" + guidance

    lines = [
        f"Title: {title}",
        f"Source: {source}",
    ]
    if file_count is not None:
        lines.append(f"Files: {file_count}")
    if files:
        lines.extend(
            [
                f"Video files: {video_count}",
                f"Collection hint: {str(collection_hint).lower()}",
            ]
        )

    lines += [
        "",
        "Next: check the library with query_library.py, run "
        "preflight_download.py, ask for explicit confirmation including any "
        "policy conflicts, then run create_download.py with the torrent URL and title. "
        "Pass the exact Collection hint value to both scripts. "
        "Pass the title verbatim — it is used by the backend to rename "
        "the file. Do NOT modify or fabricate it.",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    from openlist_ani.assistant.builtin_skills.runtime.cli import run_cli

    run_cli(run)
