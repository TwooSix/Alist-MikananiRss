from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openlist_ani.assistant.builtin_skills.runtime.confirmation import (
    CONFIRMATION_STATE_ENV,
    ConfirmationTurnState,
    issue_download_confirmation_ticket,
)

from openlist_ani.assistant.builtin_skills.plugins.oani.skills.oani.scripts import (
    create_download,
    preflight_download,
    resolve_magnet,
    resolve_torrent,
)


def _backend_client(**methods):
    return SimpleNamespace(
        **{name: AsyncMock(return_value=value) for name, value in methods.items()},
        close=AsyncMock(),
    )


@pytest.fixture(autouse=True)
def confirmation_state(tmp_path, monkeypatch) -> ConfirmationTurnState:
    state = ConfirmationTurnState(tmp_path / "confirmation-state.json")
    monkeypatch.setenv(CONFIRMATION_STATE_ENV, str(state.path))
    state.begin_turn()
    return state


@pytest.mark.asyncio
async def test_download_ticket_rejects_same_turn_and_accepts_later_user_turn(
    monkeypatch, confirmation_state
):
    client = _backend_client(
        preflight_download={
            "success": True,
            "message": "No policy conflicts",
            "confirmation_required": False,
            "policy_conflicts": [],
            "policy_warnings": [],
        },
        create_download={
            "success": True,
            "message": "Download started",
            "task": {"id": "task-turn-bound"},
        },
    )
    for module in (preflight_download, create_download):
        monkeypatch.setattr(module, "BackendClient", lambda _url: client)
        monkeypatch.setattr(
            module,
            "config",
            SimpleNamespace(backend_url="https://backend.test"),
        )
    monkeypatch.setattr(
        create_download, "_url_already_in_library", AsyncMock(return_value=None)
    )

    preflight_result = await preflight_download.run(
        download_url="magnet:?xt=urn:btih:turn-bound",
        title="Example Anime - 01",
    )
    match = re.search(r"Assistant confirmation ticket: (\S+)", preflight_result)
    assert match is not None
    ticket = match.group(1)

    same_turn = await create_download.run(
        download_url="magnet:?xt=urn:btih:turn-bound",
        title="Example Anime - 01",
        confirmed=True,
        confirmation_ticket=ticket,
    )
    assert "later user turn" in same_turn
    client.create_download.assert_not_awaited()

    confirmation_state.begin_turn()
    later_turn = await create_download.run(
        download_url="magnet:?xt=urn:btih:turn-bound",
        title="Example Anime - 01",
        confirmed=True,
        confirmation_ticket=ticket,
    )
    assert "Download created successfully" in later_turn
    client.create_download.assert_awaited_once()


@pytest.mark.asyncio
async def test_download_ticket_is_bound_to_exact_request(
    monkeypatch, confirmation_state
):
    ticket = issue_download_confirmation_ticket(
        download_url="magnet:?xt=urn:btih:request-a",
        title="Example Anime - 01",
        collection_hint=False,
        override_policy=False,
    )
    confirmation_state.begin_turn()
    backend_client = _backend_client(create_download={})
    monkeypatch.setattr(create_download, "BackendClient", lambda _url: backend_client)

    result = await create_download.run(
        download_url="magnet:?xt=urn:btih:request-a",
        title="Different title",
        confirmed=True,
        confirmation_ticket=ticket,
    )

    assert "does not match this exact download request" in result
    backend_client.create_download.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "method_name", "arguments"),
    [
        (
            resolve_magnet,
            "resolve_magnet",
            {"magnet": "magnet:?xt=urn:btih:resolved-collection"},
        ),
        (
            resolve_torrent,
            "resolve_torrent",
            {"url": "https://example.test/collection.torrent"},
        ),
    ],
)
async def test_resolver_reports_multivideo_collection_hint(
    monkeypatch, module, method_name, arguments
):
    client = _backend_client(
        **{
            method_name: {
                "success": True,
                "title": "Opaque release",
                "source": "metadata",
                "file_count": 3,
                "files": [
                    {"name": "Episode 01.mkv", "size": 100},
                    {"name": "Episode 02.mp4", "size": 101},
                    {"name": "Episode 02.ass", "size": 2},
                ],
            }
        }
    )
    monkeypatch.setattr(module, "BackendClient", lambda _url: client)
    monkeypatch.setattr(
        module,
        "config",
        SimpleNamespace(backend_url="https://backend.test"),
    )

    result = await module.run(**arguments)

    assert "Video files: 2" in result
    assert "Collection hint: true" in result
    assert "Pass the exact Collection hint value" in result


@pytest.mark.asyncio
async def test_magnet_resolver_reports_backend_runtime_failure(monkeypatch):
    client = _backend_client(
        resolve_magnet={
            "success": False,
            "message": (
                "Magnet metadata resolution is unavailable. "
                "No tracker, DHT, or peer lookup was attempted."
            ),
            "error_code": "libtorrent_unavailable",
        }
    )
    monkeypatch.setattr(resolve_magnet, "BackendClient", lambda _url: client)
    monkeypatch.setattr(
        resolve_magnet,
        "config",
        SimpleNamespace(backend_url="https://backend.test"),
    )

    result = await resolve_magnet.run(
        magnet="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567"
    )

    assert "backend dependency problem" in result
    assert "No tracker, DHT, or peer lookup was attempted" in result
    assert "supply a title as a workaround" in result


@pytest.mark.asyncio
async def test_dn_title_with_timed_out_file_inspection_is_conservative(monkeypatch):
    client = _backend_client(
        resolve_magnet={
            "success": True,
            "message": (
                "Resolved title from magnet 'dn=', but collection inspection is "
                "incomplete because metadata fetching timed out after 2s."
            ),
            "title": "Opaque release",
            "source": "dn",
            "error_code": "metadata_timeout",
            "file_count": None,
            "files": [],
        }
    )
    monkeypatch.setattr(resolve_magnet, "BackendClient", lambda _url: client)
    monkeypatch.setattr(
        resolve_magnet,
        "config",
        SimpleNamespace(backend_url="https://backend.test"),
    )

    result = await resolve_magnet.run(
        magnet="magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Opaque",
        metadata_timeout=2,
    )

    assert "Title: Opaque release" in result
    assert "Collection inspection: incomplete" in result
    assert "Collection hint: true" in result
    assert "keep the conservative true hint" in result


@pytest.mark.asyncio
async def test_invalid_magnet_requests_a_valid_link_not_a_title(monkeypatch):
    client = _backend_client(
        resolve_magnet={
            "success": False,
            "message": "Invalid magnet URI",
            "error_code": "invalid_magnet",
        }
    )
    monkeypatch.setattr(resolve_magnet, "BackendClient", lambda _url: client)
    monkeypatch.setattr(
        resolve_magnet,
        "config",
        SimpleNamespace(backend_url="https://backend.test"),
    )

    result = await resolve_magnet.run(magnet="broken")

    assert "valid magnet link" in result
    assert "title cannot repair" in result


@pytest.mark.asyncio
async def test_preflight_download_formats_conflicts_for_explicit_confirmation(
    monkeypatch,
):
    client = _backend_client(
        preflight_download={
            "success": True,
            "message": "Policy confirmation required",
            "confirmation_required": True,
            "policy_review_token": "review-token-1",
            "policy_conflicts": [
                {
                    "key": "title_pattern:collection",
                    "code": "title_pattern",
                    "reason": "Title matches an automatic collection filter",
                    "matched": "合集",
                }
            ],
            "policy_warnings": ["Only title-level policies were inspected."],
        }
    )
    monkeypatch.setattr(preflight_download, "BackendClient", lambda _url: client)
    monkeypatch.setattr(
        preflight_download,
        "config",
        SimpleNamespace(backend_url="https://backend.test"),
    )

    result = await preflight_download.run(
        download_url="magnet:?xt=urn:btih:collection",
        title="Example Anime 合集",
        collection_hint=True,
    )

    client.preflight_download.assert_awaited_once_with(
        "magnet:?xt=urn:btih:collection",
        "Example Anime 合集",
        collection_hint=True,
    )
    client.close.assert_awaited_once_with()
    assert "found overridable policy conflicts" in result
    assert "[title_pattern:collection]" in result
    assert "Title matches an automatic collection filter" in result
    assert "matched: 合集" in result
    assert "Only title-level policies were inspected." in result
    assert "No download was created." in result
    assert "override_policy=true" in result
    assert "Policy review token: review-token-1" in result
    assert "[[CONFIRMATION_REQUIRED]]" in result


@pytest.mark.asyncio
async def test_preflight_download_formats_no_conflict_result(monkeypatch):
    client = _backend_client(
        preflight_download={
            "success": True,
            "message": "No policy conflicts",
            "confirmation_required": False,
            "policy_conflicts": [],
            "policy_warnings": [],
        }
    )
    monkeypatch.setattr(preflight_download, "BackendClient", lambda _url: client)
    monkeypatch.setattr(
        preflight_download,
        "config",
        SimpleNamespace(backend_url="https://backend.test"),
    )

    result = await preflight_download.run(
        download_url="magnet:?xt=urn:btih:episode",
        title="Example Anime - 01",
    )

    client.preflight_download.assert_awaited_once_with(
        "magnet:?xt=urn:btih:episode",
        "Example Anime - 01",
        collection_hint=False,
    )
    client.close.assert_awaited_once_with()
    assert "passed with no policy conflicts" in result
    assert "No download was created." in result
    assert "normal explicit confirmation" in result
    assert "override_policy=false" in result


@pytest.mark.asyncio
async def test_create_download_formats_confirmation_required_recheck(
    monkeypatch, confirmation_state
):
    client = _backend_client(
        create_download={
            "success": False,
            "message": "Policy conflicts changed",
            "confirmation_required": True,
            "policy_review_token": "review-token-2",
            "policy_conflicts": [
                {
                    "key": "metadata_filter:quality:480p",
                    "code": "metadata_filter",
                    "reason": "Quality is excluded by the automatic policy",
                    "matched": "480p",
                }
            ],
        }
    )
    library_lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(create_download, "BackendClient", lambda _url: client)
    monkeypatch.setattr(
        create_download,
        "config",
        SimpleNamespace(backend_url="https://backend.test"),
    )
    monkeypatch.setattr(
        create_download,
        "_url_already_in_library",
        library_lookup,
    )

    confirmation_ticket = issue_download_confirmation_ticket(
        download_url="magnet:?xt=urn:btih:changed-policy",
        title="Example Anime - 01 [480p]",
        collection_hint=False,
        override_policy=True,
        acknowledged_conflicts=["title_pattern:old"],
        policy_review_token="review-token-1",
    )
    confirmation_state.begin_turn()

    result = await create_download.run(
        download_url="magnet:?xt=urn:btih:changed-policy",
        title="Example Anime - 01 [480p]",
        confirmed=True,
        override_policy=True,
        acknowledged_conflicts=["title_pattern:old"],
        policy_review_token="review-token-1",
        confirmation_ticket=confirmation_ticket,
    )

    library_lookup.assert_awaited_once_with("magnet:?xt=urn:btih:changed-policy")
    client.create_download.assert_awaited_once_with(
        "magnet:?xt=urn:btih:changed-policy",
        "Example Anime - 01 [480p]",
        collection_hint=False,
        override_policy=True,
        acknowledged_conflicts=["title_pattern:old"],
        policy_review_token="review-token-1",
    )
    client.close.assert_awaited_once_with()
    assert "was not created because policy confirmation is required" in result
    assert "[metadata_filter:quality:480p]" in result
    assert "matched: 480p" in result
    assert "Do not retry in this turn" in result
    assert "Policy review token: review-token-2" in result
    assert "[[CONFIRMATION_REQUIRED]]" in result


@pytest.mark.asyncio
async def test_create_download_forwards_confirmed_policy_override(
    monkeypatch, confirmation_state
):
    client = _backend_client(
        create_download={
            "success": True,
            "message": "Download started",
            "task": {"id": "task-123"},
            "confirmation_required": False,
            "policy_conflicts": [
                {
                    "key": "title_pattern:collection",
                    "reason": "Title matches the collection policy",
                    "matched": "合集",
                }
            ],
        }
    )
    monkeypatch.setattr(create_download, "BackendClient", lambda _url: client)
    monkeypatch.setattr(
        create_download,
        "config",
        SimpleNamespace(backend_url="https://backend.test"),
    )
    monkeypatch.setattr(
        create_download,
        "_url_already_in_library",
        AsyncMock(return_value=None),
    )

    confirmation_ticket = issue_download_confirmation_ticket(
        download_url="magnet:?xt=urn:btih:collection",
        title="Example Anime 合集",
        collection_hint=True,
        override_policy=True,
        acknowledged_conflicts=["title_pattern:collection"],
        policy_review_token="review-token-1",
    )
    confirmation_state.begin_turn()

    result = await create_download.run(
        download_url="magnet:?xt=urn:btih:collection",
        title="Example Anime 合集",
        confirmed=True,
        collection_hint=True,
        override_policy=True,
        acknowledged_conflicts=["title_pattern:collection"],
        policy_review_token="review-token-1",
        confirmation_ticket=confirmation_ticket,
    )

    client.create_download.assert_awaited_once_with(
        "magnet:?xt=urn:btih:collection",
        "Example Anime 合集",
        collection_hint=True,
        override_policy=True,
        acknowledged_conflicts=["title_pattern:collection"],
        policy_review_token="review-token-1",
    )
    client.close.assert_awaited_once_with()
    assert "Download created successfully" in result
    assert "Task ID: task-123" in result
    assert "Confirmed policy overrides" in result
    assert "[title_pattern:collection]" in result
