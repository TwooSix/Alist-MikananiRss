"""Create a new download task by magnet/torrent URL."""

from openlist_ani.assistant.builtin_skills.support.oani_backend_client import (
    BackendClient,
)
from openlist_ani.assistant.builtin_skills.runtime.confirmation import (
    confirmation_error,
    consume_download_confirmation_ticket,
    issue_download_confirmation_ticket,
)
from openlist_ani.adapters.configuration import config
from openlist_ani.assistant.builtin_skills.support.library_query import (
    SqliteAnimeLibraryQueryAdapter,
)


async def _url_already_in_library(download_url: str) -> dict | None:
    """Return the existing library row for ``download_url`` if any.

    The ``resources`` table treats ``url`` as a unique source
    identity. We refuse duplicates here as a hard guard rather than relying
    on the LLM to remember the skill rules.
    """
    query_adapter = SqliteAnimeLibraryQueryAdapter()
    sql = (
        "SELECT title, anime_name, season, episode, downloaded_at "
        "FROM resources WHERE url = ? LIMIT 1"
    )
    rows = await query_adapter.execute_sql_query(sql, (download_url,))
    if not rows:
        return None
    first = rows[0]
    if "error" in first and len(first) == 1:
        # Surface query errors as "no match" — let the backend respond
        # so we don't block downloads on a broken pre-check.
        return None
    return first


async def run(
    download_url: str = "",
    title: str = "",
    confirmed: bool = False,
    collection_hint: bool = False,
    override_policy: bool = False,
    acknowledged_conflicts: list[str] | None = None,
    policy_review_token: str | None = None,
    confirmation_ticket: str | None = None,
    **kwargs,
) -> str:
    """Submit a new download task.

    Args:
        download_url: Magnet link or torrent URL (required).
        title: Resource title for identification (required).
    """
    if error := confirmation_error(confirmed):
        return error
    if not download_url:
        return (
            "Error: 'download_url' parameter is required (magnet link or torrent URL)."
        )
    if not title:
        return "Error: 'title' parameter is required."
    if override_policy and (not acknowledged_conflicts or not policy_review_token):
        return (
            "Error: confirmed policy overrides require both exact "
            "acknowledged_conflicts and the policy_review_token returned by "
            "preflight. Run preflight_download.py again."
        )

    ticket_check = consume_download_confirmation_ticket(
        confirmation_ticket,
        download_url=download_url,
        title=title,
        collection_hint=collection_hint,
        override_policy=override_policy,
        acknowledged_conflicts=acknowledged_conflicts or (),
        policy_review_token=policy_review_token,
    )
    if not ticket_check.accepted:
        return (
            f"Confirmation required: {ticket_check.message}\n"
            "Do not retry in this turn. Show the exact operation and end the "
            "response with [[CONFIRMATION_REQUIRED]]."
        )

    existing = await _url_already_in_library(download_url)
    if existing is not None:
        return (
            "Refusing to create download: this download_url is already "
            "in the library.\n"
            f"Existing row: title={existing.get('title')!r}, "
            f"anime_name={existing.get('anime_name')!r}, "
            f"season={existing.get('season')}, "
            f"episode={existing.get('episode')}, "
            f"downloaded_at={existing.get('downloaded_at')}.\n"
            "If the user really wants to re-download this release, "
            "delete the existing row first or pick a different source URL."
        )

    client = BackendClient(config.backend_url)
    try:
        data = await client.create_download(
            download_url,
            title,
            collection_hint=collection_hint,
            override_policy=override_policy,
            acknowledged_conflicts=acknowledged_conflicts,
            policy_review_token=policy_review_token,
        )
    except Exception as e:
        return f"Error creating download: {e}"
    finally:
        await client.close()

    success = data.get("success", False)
    msg = data.get("message", "")
    task = data.get("task", {})

    if data.get("confirmation_required"):
        conflicts = data.get("policy_conflicts") or []
        refreshed_token = str(data.get("policy_review_token") or "")
        if conflicts and not refreshed_token:
            return (
                "Download was not created: the Backend requested policy "
                "confirmation without a policy review token. Run "
                "preflight_download.py again."
            )
        conflict_keys = [
            str(item.get("key") or item.get("code") or "unknown") for item in conflicts
        ]
        try:
            refreshed_confirmation_ticket = issue_download_confirmation_ticket(
                download_url=download_url,
                title=title,
                collection_hint=collection_hint,
                override_policy=True,
                acknowledged_conflicts=conflict_keys,
                policy_review_token=refreshed_token,
            )
        except RuntimeError as error:
            return (
                "Download was not created and a fresh confirmation could not be "
                f"armed: {error}"
            )
        lines = [
            "Download was not created because policy confirmation is required.",
            f"Title: {title}",
            f"Download URL: {download_url}",
            f"Collection hint: {collection_hint}",
            f"Policy review token: {refreshed_token}",
            f"Assistant confirmation ticket: {refreshed_confirmation_ticket}",
            "Policy conflicts:",
        ]
        lines.extend(_format_conflict(item) for item in conflicts)
        lines.extend(
            [
                "",
                "Do not retry in this turn. Show every current conflict to the "
                "user and ask again. After a later explicit confirmation, rerun "
                "create_download.py with the same collection_hint, confirmed=true, "
                "override_policy=true, "
                "and acknowledged_conflicts set to the exact conflict keys above. "
                "Pass policy_review_token exactly as shown above and preserve the "
                "same download URL, title, and Assistant confirmation ticket. "
                "End the confirmation request with [[CONFIRMATION_REQUIRED]].",
            ]
        )
        return "\n".join(lines)

    if success:
        task_id = task.get("id", "unknown")
        lines = [
            "Download created successfully.",
            f"Task ID: {task_id}",
            f"Title: {title}",
            msg,
        ]
        conflicts = data.get("policy_conflicts") or []
        if conflicts:
            lines.append("Confirmed policy overrides:")
            lines.extend(_format_conflict(item) for item in conflicts)
        warnings = data.get("policy_warnings") or []
        if warnings:
            lines.append(
                "Policy inspection warnings: "
                + "; ".join(str(item) for item in warnings)
            )
        return "\n".join(lines)
    else:
        return f"Failed to create download: {msg}"


def _format_conflict(item: dict) -> str:
    key = item.get("key") or item.get("code") or "unknown"
    reason = item.get("reason") or "Automatic policy conflict"
    matched = item.get("matched") or ""
    suffix = f" (matched: {matched})" if matched else ""
    return f"- [{key}] {reason}{suffix}"


if __name__ == "__main__":
    from openlist_ani.assistant.builtin_skills.runtime.cli import run_cli

    run_cli(run)
