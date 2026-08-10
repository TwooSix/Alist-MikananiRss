from __future__ import annotations

import posixpath

import pytest

from openlist_ani.application.organization import (
    DurableOrganizationExecutor,
    OrganizationError,
    StorageEntry,
    next_available_name,
)
from openlist_ani.application.ports import (
    DownloadedFile,
    DownloadManifest,
    OrganizationRequest,
    OrganizationSidecar,
)
from openlist_ani.domain import DownloadJob, MetadataDocument, ReleaseCandidate


class MemoryStorage:
    backend_name = "memory"

    def __init__(self):
        self.directories = {
            "/stage/job": {"raw.mkv", "raw.zh.ass", "ignored.txt"},
            "/library/Example/Season 1": {"Example S01E01.mkv"},
        }
        self.sizes = {
            "/stage/job/raw.mkv": 100,
            "/stage/job/raw.zh.ass": 10,
            "/stage/job/ignored.txt": 1,
            "/library/Example/Season 1/Example S01E01.mkv": 999,
        }
        self.cleanup_calls = []

    def join(self, root, *parts):
        return posixpath.join(root, *parts)

    async def list_directory(self, path):
        return tuple(
            StorageEntry(name, size=self.sizes.get(self.join(path, name), 0))
            for name in sorted(self.directories.get(path, set()))
        )

    async def ensure_directory(self, _base_path, target_path):
        self.directories.setdefault(target_path, set())

    async def rename(self, full_path, new_name):
        parent, name = posixpath.split(full_path)
        self.directories[parent].remove(name)
        self.directories[parent].add(new_name)
        size = self.sizes.pop(self.join(parent, name), 0)
        self.sizes[self.join(parent, new_name)] = size

    async def move(self, source_directory, target_directory, filenames):
        for name in filenames:
            self.directories[source_directory].remove(name)
            self.directories[target_directory].add(name)
            size = self.sizes.pop(self.join(source_directory, name), 0)
            self.sizes[self.join(target_directory, name)] = size

    async def remove_files(self, directory, filenames):
        for name in filenames:
            self.directories[directory].discard(name)
            self.sizes.pop(self.join(directory, name), None)

    async def remove_staging_tree(self, path, *, job_id, base_path):
        assert path == f"/stage/{job_id}"
        assert base_path == "/library"
        self.cleanup_calls.append(path)
        self.directories.pop(path, None)
        for full_path in tuple(self.sizes):
            if full_path == path or full_path.startswith(path.rstrip("/") + "/"):
                self.sizes.pop(full_path)


def _job():
    candidate = ReleaseCandidate.create(
        source_name="test",
        source_url="https://example.test/rss",
        title="Example collection",
        download_url="magnet:example",
    )
    return DownloadJob(
        id="job",
        candidate=candidate,
        artifact={"base_path": "/library"},
    )


@pytest.mark.asyncio
async def test_executor_persists_plan_moves_sidecars_and_cleans_staging():
    storage = MemoryStorage()
    executor = DurableOrganizationExecutor(storage)
    job = _job()
    manifest = DownloadManifest(
        root_path="/stage/job",
        cleanup_root="/stage/job",
        files=(
            DownloadedFile("raw.mkv", 100),
            DownloadedFile("raw.zh.ass", 10),
            DownloadedFile("ignored.txt", 1),
        ),
    )
    request = OrganizationRequest(
        item_key="s01e01",
        video_relative_path="raw.mkv",
        sidecars=(OrganizationSidecar("raw.zh.ass", ".zh"),),
        target_directory_path="/library/Example/Season 1",
        target_filename="Example S01E01.mkv",
        metadata=MetadataDocument(),
    )
    checkpoints = []

    async def checkpoint(payload):
        checkpoints.append(payload)
        job.artifact["organization_checkpoint"] = payload

    results = await executor.organize(job, manifest, (request,), checkpoint)

    assert results[0].state == "completed"
    assert results[0].final_path == "/library/Example/Season 1/Example S01E01 (1).mkv"
    assert results[0].sidecar_paths == (
        "/library/Example/Season 1/Example S01E01 (1).zh.ass",
    )
    assert checkpoints[0]["plans"][0]["state"] == "pending"
    assert any(
        checkpoint["plans"][0]["state"] == "pending"
        and checkpoint["plans"][0]["files"][0]["state"] == "completed"
        and checkpoint["plans"][0]["files"][1]["state"] == "pending"
        for checkpoint in checkpoints
    )
    assert checkpoints[-1]["cleanup_state"] == "completed"
    assert storage.cleanup_calls == ["/stage/job"]


def test_conflict_names_are_backend_neutral_and_bounded():
    assert next_available_name("episode.mkv", set()) == "episode.mkv"
    assert next_available_name("episode.mkv", {"episode.mkv"}) == "episode (1).mkv"


@pytest.mark.asyncio
async def test_legacy_source_is_not_treated_as_its_own_name_conflict():
    storage = MemoryStorage()
    directory = "/library/Legacy/Season 1"
    storage.directories[directory] = {"Legacy S01E01.mkv"}
    storage.sizes[f"{directory}/Legacy S01E01.mkv"] = 100
    executor = DurableOrganizationExecutor(storage)
    job = _job()
    manifest = DownloadManifest(
        root_path=directory,
        files=(DownloadedFile("Legacy S01E01.mkv"),),
        legacy_materialized=True,
    )
    request = OrganizationRequest(
        item_key="legacy",
        video_relative_path="Legacy S01E01.mkv",
        sidecars=(),
        target_directory_path=directory,
        target_filename="Legacy S01E01.mkv",
        metadata=MetadataDocument(),
    )

    result = await executor.organize(job, manifest, (request,))

    assert result[0].final_path == f"{directory}/Legacy S01E01.mkv"
    assert storage.directories[directory] == {"Legacy S01E01.mkv"}


@pytest.mark.asyncio
async def test_staging_sibling_cannot_be_overwritten_during_prepare_rename():
    storage = MemoryStorage()
    storage.directories["/stage/job"] = {"raw.mkv", "Example S01E02.mkv"}
    storage.directories["/library/Example/Season 1"] = set()
    executor = DurableOrganizationExecutor(storage)
    job = _job()
    manifest = DownloadManifest(
        root_path="/stage/job",
        cleanup_root="/stage/job",
        files=(
            DownloadedFile("raw.mkv", 100),
            DownloadedFile("Example S01E02.mkv", 90),
        ),
    )
    request = OrganizationRequest(
        item_key="s01e02",
        video_relative_path="raw.mkv",
        sidecars=(),
        target_directory_path="/library/Example/Season 1",
        target_filename="Example S01E02.mkv",
        metadata=MetadataDocument(),
    )

    result = await executor.organize(job, manifest, (request,))

    assert result[0].final_path.endswith("/Example S01E02 (1).mkv")


class FailingSubtitleStorage(MemoryStorage):
    async def move(self, source_directory, target_directory, filenames):
        if any(name.endswith(".ass") for name in filenames):
            raise RuntimeError("subtitle move failed")
        await super().move(source_directory, target_directory, filenames)


@pytest.mark.asyncio
async def test_terminal_item_failure_removes_only_its_materialized_targets():
    storage = FailingSubtitleStorage()
    executor = DurableOrganizationExecutor(storage)
    job = _job()
    manifest = DownloadManifest(
        root_path="/stage/job",
        cleanup_root="/stage/job",
        files=(
            DownloadedFile("raw.mkv", 100),
            DownloadedFile("raw.zh.ass", 10),
            DownloadedFile("ignored.txt", 1),
        ),
    )
    request = OrganizationRequest(
        item_key="s01e01",
        video_relative_path="raw.mkv",
        sidecars=(OrganizationSidecar("raw.zh.ass", ".zh"),),
        target_directory_path="/library/Example/Season 1",
        target_filename="Example S01E01.mkv",
        metadata=MetadataDocument(),
    )

    async def checkpoint(payload):
        job.artifact["organization_checkpoint"] = payload

    with pytest.raises(RuntimeError, match="subtitle move failed"):
        await executor.organize(job, manifest, (request,), checkpoint)
    with pytest.raises(RuntimeError, match="subtitle move failed"):
        await executor.organize(job, manifest, (request,), checkpoint)
    results = await executor.organize(job, manifest, (request,), checkpoint)

    assert results[0].state == "failed"
    assert results[0].final_path is None
    # The pre-existing conflict remains, while the organizer-owned (1) target
    # is rolled back before staging cleanup.
    assert storage.directories["/library/Example/Season 1"] == {"Example S01E01.mkv"}
    assert storage.cleanup_calls == ["/stage/job"]


@pytest.mark.asyncio
async def test_failed_item_never_deletes_a_target_with_changed_fingerprint():
    storage = FailingSubtitleStorage()
    executor = DurableOrganizationExecutor(storage)
    job = _job()
    manifest = DownloadManifest(
        root_path="/stage/job",
        cleanup_root="/stage/job",
        files=(
            DownloadedFile("raw.mkv", 100),
            DownloadedFile("raw.zh.ass", 10),
        ),
    )
    request = OrganizationRequest(
        item_key="s01e01",
        video_relative_path="raw.mkv",
        sidecars=(OrganizationSidecar("raw.zh.ass", ".zh"),),
        target_directory_path="/library/Example/Season 1",
        target_filename="Example S01E01.mkv",
        metadata=MetadataDocument(),
    )

    async def checkpoint(payload):
        job.artifact["organization_checkpoint"] = payload

    with pytest.raises(OrganizationError, match="subtitle move failed"):
        await executor.organize(job, manifest, (request,), checkpoint)
    with pytest.raises(OrganizationError, match="subtitle move failed"):
        await executor.organize(job, manifest, (request,), checkpoint)

    replacement = "/library/Example/Season 1/Example S01E01 (1).mkv"
    storage.sizes[replacement] = 101
    with pytest.raises(OrganizationError, match="fingerprint changed"):
        await executor.organize(job, manifest, (request,), checkpoint)

    assert "Example S01E01 (1).mkv" in storage.directories["/library/Example/Season 1"]
    assert storage.cleanup_calls == []


@pytest.mark.asyncio
async def test_target_directory_must_be_a_strict_child_of_base_path():
    storage = MemoryStorage()
    executor = DurableOrganizationExecutor(storage)
    manifest = DownloadManifest(
        root_path="/stage/job",
        cleanup_root="/stage/job",
        files=(DownloadedFile("raw.mkv", 100),),
    )
    request = OrganizationRequest(
        item_key="escape",
        video_relative_path="raw.mkv",
        sidecars=(),
        target_directory_path="/library/../outside",
        target_filename="escaped.mkv",
        metadata=MetadataDocument(),
    )

    with pytest.raises(OrganizationError, match="Unsafe organization target"):
        await executor.organize(_job(), manifest, (request,))

    assert "/outside" not in storage.directories
