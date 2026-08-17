"""Parse an RSS feed and return its resource entries.

Calls the backend ``/api/parse_rss`` endpoint, which reuses the same feed
sources used by the RSS monitor. The assistant should pick desired entries
and then follow the anime-download confirmation workflow.
"""

from openlist_ani.assistant.builtin_skills.support.oani_backend_client import (
    BackendClient,
)
from openlist_ani.adapters.configuration import config


async def run(
    url: str = "",
    limit: int | None = None,
    **kwargs,
) -> str:
    """Parse an RSS feed.

    Args:
        url: RSS feed URL (required).
        limit: Optional max number of entries to return.
    """
    if not url:
        return "Error: 'url' parameter is required (RSS feed URL)."

    client = BackendClient(config.backend_url)
    try:
        data = await client.parse_rss(url, limit=limit)
    except Exception as e:
        return f"Error parsing RSS: {e}"
    finally:
        await client.close()

    if not data.get("success", False):
        return f"Failed to parse RSS: {data.get('message', 'unknown error')}"

    entries = data.get("entries", [])
    total = data.get("total", len(entries))
    if not entries:
        return f"No entries parsed from {url}."

    lines = [
        f"Parsed {len(entries)} of {total} entries from {url}.",
        "",
        "| # | Title | Fansub | Quality | Lang | Magnet/Torrent |",
        "|---|---|---|---|---|---|",
    ]
    for e in entries:
        idx = e.get("index", "?")
        title = (e.get("title") or "").replace("|", "\\|")
        fansub = e.get("fansub") or "-"
        quality = e.get("quality") or "-"
        langs = ",".join(e.get("languages") or []) or "-"
        download_url = e.get("download_url") or ""
        lines.append(
            f"| {idx} | {title} | {fansub} | {quality} | {langs} | {download_url} |"
        )

    lines += [
        "",
        "Next: pick entries, check duplicates, run preflight_download.py for each "
        "candidate, ask for confirmation including any policy conflicts, then run "
        "create_download.py for each confirmed item. Pass the canonical title "
        "verbatim and do not modify it.",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    from openlist_ani.assistant.builtin_skills.runtime.cli import run_cli

    run_cli(run)
