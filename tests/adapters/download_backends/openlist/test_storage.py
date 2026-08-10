from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from openlist_ani.adapters.download_backends.openlist.storage import (
    OpenListStorageOperations,
)
from openlist_ani.application.organization import OrganizationError


@pytest.mark.asyncio
async def test_remove_files_deletes_only_named_target_and_verifies_result():
    client = AsyncMock()
    client.list_files = AsyncMock(
        side_effect=[
            [
                SimpleNamespace(name="pre-existing.mkv"),
                SimpleNamespace(name="owned-target.mkv"),
            ],
            [SimpleNamespace(name="pre-existing.mkv")],
        ]
    )
    client.remove_path = AsyncMock(return_value=True)
    storage = OpenListStorageOperations(client, AsyncMock())

    await storage.remove_files("/library/Example", ("owned-target.mkv",))

    client.remove_path.assert_awaited_once_with(
        "/library/Example", ["owned-target.mkv"]
    )


@pytest.mark.asyncio
async def test_remove_staging_requires_exact_base_job_path_and_verifies_absence():
    client = AsyncMock()
    client.remove_path = AsyncMock(return_value=True)
    client.list_files = AsyncMock(return_value=[])
    storage = OpenListStorageOperations(client, AsyncMock(), cache_refresh_seconds=0)

    await storage.remove_staging_tree(
        "/library/.oani-download-tmp/job-1",
        job_id="job-1",
        base_path="/library",
    )

    client.remove_path.assert_awaited_once_with(
        "/library/.oani-download-tmp", ["job-1"]
    )
    client.list_files.assert_awaited_once_with("/library/.oani-download-tmp")


@pytest.mark.asyncio
async def test_remove_staging_rejects_same_shape_below_a_different_root():
    client = AsyncMock()
    storage = OpenListStorageOperations(client, AsyncMock(), cache_refresh_seconds=0)

    with pytest.raises(OrganizationError, match="unsafe OpenList staging"):
        await storage.remove_staging_tree(
            "/other/.oani-download-tmp/job-1",
            job_id="job-1",
            base_path="/library",
        )

    client.remove_path.assert_not_awaited()


@pytest.mark.asyncio
async def test_remove_staging_does_not_trust_success_while_directory_is_visible():
    client = AsyncMock()
    client.remove_path = AsyncMock(return_value=True)
    client.list_files = AsyncMock(return_value=[SimpleNamespace(name="job-1")])
    storage = OpenListStorageOperations(client, AsyncMock(), cache_refresh_seconds=0)

    with pytest.raises(OrganizationError, match="Failed to remove staging"):
        await storage.remove_staging_tree(
            "/library/.oani-download-tmp/job-1",
            job_id="job-1",
            base_path="/library",
        )


@pytest.mark.asyncio
async def test_storage_rejects_target_directory_outside_base_path():
    client = AsyncMock()
    storage = OpenListStorageOperations(client, AsyncMock(), cache_refresh_seconds=0)

    with pytest.raises(Exception, match="target directory"):
        await storage.ensure_directory("/library", "/library/../outside")

    client.mkdir.assert_not_awaited()
