"""Resolve a magnet link to its real title.

Calls the backend ``/api/resolve_magnet`` endpoint. The magnet's ``dn=``
parameter can supply the title, but the backend still inspects libtorrent
metadata (DHT/peers, time-bounded) to identify collections before download.
Collection policy handling remains outside the resolver.
"""

from pathlib import PurePosixPath

from openlist_ani.application.collection import VIDEO_EXTENSIONS
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
            and file-list fetch. Defaults to 30.
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
    files = data.get("files") or []
    error_code = data.get("error_code")
    inspection_incomplete = error_code in {
        "libtorrent_unavailable",
        "metadata_fetch_failed",
        "metadata_timeout",
        "file_list_unavailable",
    }
    video_count = sum(
        PurePosixPath(str(item.get("name") or "")).suffix.lower() in VIDEO_EXTENSIONS
        for item in files
        if isinstance(item, dict)
    )
    # Unknown must not be represented as a clean single-file result.  Passing a
    # conservative true hint makes preflight request the blanket collection
    # acknowledgement before any payload is downloaded.
    collection_hint = video_count > 1 or inspection_incomplete
    msg = data.get("message", "")

    if not success:
        if error_code == "libtorrent_unavailable":
            return (
                f"Failed to resolve magnet: {msg}\n"
                "This is a backend dependency problem, not missing information "
                "from the user. Report the error and do NOT ask the user to "
                "supply a title as a workaround."
            )
        if error_code == "invalid_magnet":
            return (
                f"Failed to resolve magnet: {msg}\n"
                "Ask the user for a valid magnet link. Supplying a title cannot "
                "repair an invalid URI."
            )
        if error_code in {"metadata_timeout", "metadata_fetch_failed"}:
            return (
                f"Failed to resolve magnet: {msg}\n"
                "The user may supply the exact resource title, but file/collection "
                "inspection remains incomplete. If they continue, disclose that "
                "warning and pass collection_hint=true to preflight_download.py "
                "and create_download.py; do NOT claim the resource is a single file."
            )
        return (
            f"Failed to resolve magnet: {msg}\n"
            "Report this resolver error as-is; do NOT claim that merely supplying "
            "a title will fix it."
        )

    lines = [
        f"Title: {title}",
        f"Source: {source}",
    ]
    if file_count is not None:
        lines.append(f"Files: {file_count}")
    if inspection_incomplete:
        lines.extend(
            [
                "Collection inspection: incomplete",
                f"Inspection warning: {msg}",
                "Collection hint: true",
            ]
        )
    else:
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
        "policy conflicts, then run create_download.py with the magnet and title. "
        "Pass the exact Collection hint value to both scripts. "
        "When collection inspection is incomplete, show the warning and keep the "
        "conservative true hint so preflight cannot report a clean inspection. "
        "Pass the title verbatim — it is used by the backend to rename "
        "the file. Do NOT modify or fabricate it.",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    from openlist_ani.assistant.builtin_skills.runtime.cli import run_cli

    run_cli(run)
