"""Inspect policy conflicts before creating a manual download."""

from openlist_ani.adapters.configuration import config
from openlist_ani.assistant.builtin_skills.support.oani_backend_client import (
    BackendClient,
)
from openlist_ani.assistant.builtin_skills.runtime.confirmation import (
    issue_download_confirmation_ticket,
)


async def run(
    download_url: str = "",
    title: str = "",
    collection_hint: bool = False,
    **kwargs,
) -> str:
    """Run a read-only manual-download policy review."""

    if not download_url:
        return "Error: 'download_url' parameter is required."
    if not title:
        return "Error: 'title' parameter is required."

    client = BackendClient(config.backend_url)
    try:
        data = await client.preflight_download(
            download_url, title, collection_hint=collection_hint
        )
    except Exception as error:
        return f"Error reviewing download policy: {error}"
    finally:
        await client.close()

    if not data.get("success", False):
        return (
            f"Manual download preflight was blocked: {data.get('message', 'unknown error')}\n"
            "This is not an overridable RSS policy conflict. Do not ask for a "
            "policy override."
        )

    conflicts = data.get("policy_conflicts") or []
    warnings = data.get("policy_warnings") or []
    policy_review_token = str(data.get("policy_review_token") or "")
    if not conflicts:
        try:
            confirmation_ticket = issue_download_confirmation_ticket(
                download_url=download_url,
                title=title,
                collection_hint=collection_hint,
                override_policy=False,
            )
        except RuntimeError as error:
            return f"Manual download preflight could not arm confirmation: {error}"
        lines = [
            "Manual download preflight passed with no policy conflicts.",
            f"Title: {title}",
            f"Download URL: {download_url}",
            f"Collection hint: {collection_hint}",
            f"Assistant confirmation ticket: {confirmation_ticket}",
            "No download was created.",
        ]
        if warnings:
            lines.append(
                "Inspection warnings: " + "; ".join(str(item) for item in warnings)
            )
        lines.append(
            "Ask for the normal explicit confirmation. After a later confirmation, "
            "run create_download.py with confirmed=true, override_policy=false, "
            "and the exact Assistant confirmation ticket above."
        )
        return "\n".join(lines)

    if not policy_review_token:
        return (
            "Manual download preflight was unsafe: the Backend returned policy "
            "conflicts without a policy review token. Do not create the download."
        )

    conflict_keys = [
        str(item.get("key") or item.get("code") or "unknown") for item in conflicts
    ]
    try:
        confirmation_ticket = issue_download_confirmation_ticket(
            download_url=download_url,
            title=title,
            collection_hint=collection_hint,
            override_policy=True,
            acknowledged_conflicts=conflict_keys,
            policy_review_token=policy_review_token,
        )
    except RuntimeError as error:
        return f"Manual download preflight could not arm confirmation: {error}"

    lines = [
        "Manual download preflight found overridable policy conflicts.",
        f"Title: {title}",
        f"Download URL: {download_url}",
        f"Collection hint: {collection_hint}",
        f"Policy review token: {policy_review_token}",
        f"Assistant confirmation ticket: {confirmation_ticket}",
        "Policy conflicts:",
    ]
    lines.extend(_format_conflict(item) for item in conflicts)
    if warnings:
        lines.append(
            "Inspection warnings: " + "; ".join(str(item) for item in warnings)
        )
    lines.extend(
        [
            "",
            "No download was created. Show every conflict above to the user and "
            "ask whether to continue anyway. Do not run create_download.py in "
            "this turn. After a later explicit confirmation, run it with "
            "confirmed=true, override_policy=true, and acknowledged_conflicts "
            "set to the exact conflict keys above, plus policy_review_token set "
            "to the exact opaque token above. Preserve the exact download URL, "
            "title, collection_hint, and Assistant confirmation ticket. The "
            "ticket is rejected in this turn and can only be consumed after a "
            "later user message. End the confirmation request with "
            "[[CONFIRMATION_REQUIRED]].",
        ]
    )
    return "\n".join(lines)


def _format_conflict(item: dict) -> str:
    key = item.get("key") or item.get("code") or "unknown"
    reason = item.get("reason") or "Automatic policy conflict"
    matched = item.get("matched") or ""
    suffix = f" (matched: {matched})" if matched else ""
    return f"- [{key}] {reason}{suffix}"


if __name__ == "__main__":
    from openlist_ani.assistant.builtin_skills.runtime.cli import run_cli

    run_cli(run)
