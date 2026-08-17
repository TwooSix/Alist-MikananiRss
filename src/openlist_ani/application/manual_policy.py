"""Read-only policy review for manually submitted downloads."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from openlist_ani.application.metadata_pipeline import MetadataPipelineResolver
from openlist_ani.application.ports import JobRepository, LibraryRepository
from openlist_ani.application.settings import CoreSettings, MetadataFilterSettings
from openlist_ani.domain import (
    DownloadJob,
    JobStatus,
    LanguageType,
    MetadataDocument,
    ReleaseCandidate,
    ReleaseMetadata,
    VideoQuality,
)
from openlist_ani.domain.naming import ReleaseFilenamePlanner
from openlist_ani.domain.policies import (
    collection_title_reason,
    dominated_by_records,
    episode_key,
)

COLLECTION_POLICY_CONFLICT_KEY = "collection:automatic-release-policy"
MANUAL_PARTIAL_COLLECTION_RETRY_KEY = "manual_partial_collection_retry"
_NON_RETRYABLE_COLLECTION_ERRORS = frozenset({"already_downloaded", "not_main_episode"})


@dataclass(frozen=True)
class ManualPolicyConflict:
    """One automatic RSS policy that a manual request may override."""

    key: str
    code: str
    reason: str
    matched: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "code": self.code,
            "reason": self.reason,
            "matched": self.matched,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class ManualPolicyReview:
    """Policy review result produced without creating a durable job."""

    conflicts: tuple[ManualPolicyConflict, ...] = ()
    warnings: tuple[str, ...] = ()
    metadata: MetadataDocument = field(default_factory=MetadataDocument)

    @property
    def conflict_keys(self) -> tuple[str, ...]:
        return tuple(item.key for item in self.conflicts)


@dataclass(frozen=True)
class ManualPartialCollectionRetry:
    """Durable scope for retrying only unfinished children of a collection."""

    source_job_ids: tuple[str, ...]
    completed_item_keys: tuple[str, ...]
    completed_episode_keys: tuple[tuple[str, int, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_job_ids": list(self.source_job_ids),
            "completed_item_keys": list(self.completed_item_keys),
            "completed_episode_keys": [
                {
                    "anime_name": anime_name,
                    "season": season,
                    "episode": episode,
                }
                for anime_name, season, episode in self.completed_episode_keys
            ],
        }

    @classmethod
    def from_dict(cls, payload: Any) -> ManualPartialCollectionRetry | None:
        if not isinstance(payload, dict):
            return None
        source_job_ids = _nonempty_strings(payload.get("source_job_ids"))
        if not source_job_ids:
            return None
        return cls(
            source_job_ids=source_job_ids,
            completed_item_keys=_nonempty_strings(payload.get("completed_item_keys")),
            completed_episode_keys=_episode_keys(payload.get("completed_episode_keys")),
        )


class ManualDownloadPolicyInspector:
    """Evaluate automatic release policies before a manual task is created."""

    def __init__(
        self,
        *,
        jobs: JobRepository,
        library: LibraryRepository,
        metadata_resolver: MetadataPipelineResolver,
        settings: CoreSettings,
    ) -> None:
        self._jobs = jobs
        self._library = library
        self._metadata_resolver = metadata_resolver
        self._settings = settings
        self._filename_planner = ReleaseFilenamePlanner(settings.rename_format)

    async def inspect(
        self,
        download_url: str,
        title: str,
        *,
        collection_hint: bool = False,
    ) -> ManualPolicyReview:
        candidate = ReleaseCandidate.create(
            source_name="manual",
            source_url="api",
            title=title,
            download_url=download_url,
        )
        conflicts = self._title_conflicts(title)

        # A collection's episode-level policy can only be evaluated after the
        # backend materializes its manifest.  Make that limitation explicit and
        # obtain one blanket acknowledgement instead of silently filtering files
        # after the user has approved the parent link.
        marker = collection_title_reason(title)
        if collection_hint or marker:
            conflicts.append(
                ManualPolicyConflict(
                    key=COLLECTION_POLICY_CONFLICT_KEY,
                    code="collection_policy_override",
                    reason=(
                        "This is a collection. Continuing manually will bypass "
                        "RSS filter, priority and strict rules for its main episode files."
                    ),
                    matched=(
                        marker
                        or "resolved download metadata contains multiple video files"
                    ),
                )
            )
            return ManualPolicyReview(conflicts=_unique_conflicts(conflicts))

        try:
            resolution = (
                await self._metadata_resolver.resolve_many(
                    [candidate], [MetadataDocument()], [0]
                )
            )[0]
        except Exception as error:
            warning = f"Policy metadata inspection failed: {error}"
            conflicts.append(_inspection_conflict(warning))
            return ManualPolicyReview(
                conflicts=_unique_conflicts(conflicts),
                warnings=(warning,),
            )

        document = resolution.document
        warnings = tuple(
            item
            for item in (resolution.retryable_error, resolution.permanent_error)
            if item
        )
        if not document.values.minimum_complete():
            incomplete_warnings = warnings or (
                "Metadata is incomplete for policy inspection.",
            )
            conflicts.append(_inspection_conflict("; ".join(incomplete_warnings)))
            return ManualPolicyReview(
                conflicts=_unique_conflicts(conflicts),
                warnings=incomplete_warnings,
                metadata=document,
            )

        conflicts.extend(self._metadata_conflicts(document.values))
        conflicts.extend(await self._existing_release_conflicts(document.values))
        if warnings:
            conflicts.append(_inspection_conflict("; ".join(warnings)))
        return ManualPolicyReview(
            conflicts=_unique_conflicts(conflicts),
            warnings=warnings,
            metadata=document,
        )

    def _title_conflicts(self, title: str) -> list[ManualPolicyConflict]:
        return [
            ManualPolicyConflict(
                key=f"title_pattern:{pattern}",
                code="excluded_title_pattern",
                reason="The title matches an RSS exclusion pattern.",
                matched=pattern,
                details={"title": title},
            )
            for pattern in self._settings.metadata_filter.exclude_patterns
            if re.search(pattern, title)
        ]

    def _metadata_conflicts(
        self, metadata: ReleaseMetadata
    ) -> list[ManualPolicyConflict]:
        settings = self._settings.metadata_filter
        matches: list[tuple[str, str, str]] = []
        if metadata.fansub and metadata.fansub in set(settings.exclude_fansub):
            matches.append(("fansub", metadata.fansub, "excluded_fansub"))
        if metadata.quality and metadata.quality.value in set(settings.exclude_quality):
            matches.append(("quality", metadata.quality.value, "excluded_quality"))
        excluded_languages = set(settings.exclude_languages)
        matches.extend(
            ("language", language.value, "excluded_language")
            for language in metadata.languages
            if language.value in excluded_languages
        )
        return [
            ManualPolicyConflict(
                key=f"metadata:{field_name}={value}",
                code=code,
                reason=(
                    "The parsed release metadata is excluded by rss.filter "
                    f"({field_name}={value})."
                ),
                matched=value,
            )
            for field_name, value, code in matches
        ]

    async def _existing_release_conflicts(
        self, metadata: ReleaseMetadata
    ) -> list[ManualPolicyConflict]:
        key = episode_key(metadata)
        if key is None:
            return []
        records = await self._library.find_releases_by_episodes([key])
        active = _active_records(await self._jobs.list_active()).get(key, [])
        known = [*records.get(key, []), *active]
        conflicts: list[ManualPolicyConflict] = []
        priority = self._settings.priority
        if dominated_by_records(
            metadata,
            known,
            field_order=priority.field_order,
            fansubs=priority.fansub,
            qualities=priority.quality,
            languages=priority.languages,
        ):
            conflicts.append(
                ManualPolicyConflict(
                    key="priority:dominated",
                    code="lower_priority",
                    reason=(
                        "A downloaded or active release has higher configured RSS priority."
                    ),
                    matched=_episode_label(key),
                )
            )
        if self._settings.strict_filtering and _strict_conflict(
            metadata, known, self._filename_planner
        ):
            conflicts.append(
                ManualPolicyConflict(
                    key="strict:rename-stem-conflict",
                    code="strict_rename_conflict",
                    reason=(
                        "The release conflicts with an existing rename target under rss.strict."
                    ),
                    matched=self._filename_planner.stem(
                        metadata, include_version=False
                    ),
                )
            )
        return conflicts


def manual_policy_is_approved(job: DownloadJob) -> bool:
    """Return whether a manual job passed the explicit policy-review boundary."""

    if job.candidate.source_name != "manual":
        return False
    review = job.artifact.get("manual_policy_review")
    return isinstance(review, dict) and review.get("approved") is True


def manual_policy_acknowledges(
    job: DownloadJob, conflict_keys: tuple[str, ...]
) -> bool:
    """Return whether this review explicitly approved every supplied conflict."""

    if not conflict_keys or not manual_policy_is_approved(job):
        return False
    review = job.artifact.get("manual_policy_review")
    if not isinstance(review, dict):
        return False
    acknowledged = review.get("acknowledged_conflicts")
    if review.get("override_policy") is not True or not isinstance(acknowledged, list):
        return False
    approved_keys = {item for item in acknowledged if isinstance(item, str) and item}
    return set(conflict_keys).issubset(approved_keys)


def matching_title_policy_keys(title: str, patterns: list[str]) -> tuple[str, ...]:
    """Return stable acknowledgement keys for all matching title rules."""

    return tuple(
        f"title_pattern:{pattern}" for pattern in patterns if re.search(pattern, title)
    )


def matching_metadata_policy_keys(
    metadata: ReleaseMetadata, settings: MetadataFilterSettings
) -> tuple[str, ...]:
    """Return stable acknowledgement keys for every matching metadata rule."""

    keys: list[str] = []
    if metadata.fansub and metadata.fansub in set(settings.exclude_fansub):
        keys.append(f"metadata:fansub={metadata.fansub}")
    if metadata.quality and metadata.quality.value in set(settings.exclude_quality):
        keys.append(f"metadata:quality={metadata.quality.value}")
    excluded_languages = set(settings.exclude_languages)
    keys.extend(
        f"metadata:language={language.value}"
        for language in metadata.languages
        if language.value in excluded_languages
    )
    return tuple(keys)


def find_manual_partial_collection_retry(
    jobs: list[DownloadJob], download_url: str, title: str
) -> ManualPartialCollectionRetry | None:
    """Find unfinished collection children while retaining completed identities."""

    matches = _matching_completed_collections(jobs, download_url, title)
    if not matches:
        return None

    completed_item_keys: set[str] = set()
    completed_episode_keys: set[tuple[str, int, int]] = set()
    gap_jobs: list[DownloadJob] = []
    gap_items: list[dict[str, Any]] = []
    for job in matches:
        summary = _collection_summary(job)
        if summary is None:
            continue
        items = _summary_items(summary)
        item_keys, episode_keys = _completed_summary_identities(items)
        completed_item_keys.update(item_keys)
        completed_episode_keys.update(episode_keys)
        retryable = [item for item in items if _summary_item_is_retryable(item)]
        if retryable:
            gap_jobs.append(job)
            gap_items.extend(retryable)

    has_unfinished_child = any(
        not _summary_item_was_completed(
            item,
            completed_item_keys=completed_item_keys,
            completed_episode_keys=completed_episode_keys,
        )
        for item in gap_items
    )
    if not gap_jobs or not has_unfinished_child:
        return None
    return ManualPartialCollectionRetry(
        source_job_ids=tuple(dict.fromkeys(job.id for job in gap_jobs)),
        completed_item_keys=tuple(sorted(completed_item_keys)),
        completed_episode_keys=tuple(sorted(completed_episode_keys)),
    )


def _matching_completed_collections(
    jobs: list[DownloadJob], download_url: str, title: str
) -> list[DownloadJob]:
    completed = [
        job
        for job in jobs
        if job.status == JobStatus.COMPLETED
        and _collection_summary(job) is not None
        and (job.candidate.download_url == download_url or job.candidate.title == title)
    ]
    exact_url = [job for job in completed if job.candidate.download_url == download_url]
    return exact_url or [job for job in completed if job.candidate.title == title]


def _completed_summary_identities(
    items: list[dict[str, Any]],
) -> tuple[set[str], set[tuple[str, int, int]]]:
    item_keys: set[str] = set()
    episode_keys: set[tuple[str, int, int]] = set()
    for item in items:
        if item.get("state") != "completed":
            continue
        if item_key := _nonempty_string(item.get("item_key")):
            item_keys.add(item_key)
        if episode_key_value := _summary_episode_key(item):
            episode_keys.add(episode_key_value)
    return item_keys, episode_keys


def manual_partial_collection_retry_from_artifact(
    artifact: dict[str, Any] | None,
) -> ManualPartialCollectionRetry | None:
    """Read and validate a durable partial-collection retry scope."""

    if not isinstance(artifact, dict):
        return None
    return ManualPartialCollectionRetry.from_dict(
        artifact.get(MANUAL_PARTIAL_COLLECTION_RETRY_KEY)
    )


def collection_summary_has_retryable_gaps(summary: Any) -> bool:
    """Return whether a completed collection still has a main child to retry."""

    return bool(
        isinstance(summary, dict)
        and summary.get("collection") is True
        and any(_summary_item_is_retryable(item) for item in _summary_items(summary))
    )


def _collection_summary(job: DownloadJob) -> dict[str, Any] | None:
    summary = job.artifact.get("summary")
    if not isinstance(summary, dict) or summary.get("collection") is not True:
        return None
    return summary


def _summary_items(summary: dict[str, Any]) -> list[dict[str, Any]]:
    value = summary.get("items")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _summary_item_is_retryable(item: dict[str, Any]) -> bool:
    if item.get("state") == "completed":
        return False
    return item.get("error") not in _NON_RETRYABLE_COLLECTION_ERRORS


def _summary_item_was_completed(
    item: dict[str, Any],
    *,
    completed_item_keys: set[str],
    completed_episode_keys: set[tuple[str, int, int]],
) -> bool:
    item_key = _nonempty_string(item.get("item_key"))
    if item_key and item_key in completed_item_keys:
        return True
    episode = _summary_episode_key(item)
    return episode is not None and episode in completed_episode_keys


def _summary_episode_key(item: dict[str, Any]) -> tuple[str, int, int] | None:
    anime_name = _nonempty_string(item.get("anime_name"))
    season = item.get("season")
    episode = item.get("episode")
    if (
        not anime_name
        or not isinstance(season, int)
        or isinstance(season, bool)
        or season <= 0
        or not isinstance(episode, int)
        or isinstance(episode, bool)
        or episode <= 0
    ):
        return None
    return anime_name, season, episode


def _nonempty_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        dict.fromkeys(item for item in value if isinstance(item, str) and item)
    )


def _episode_keys(value: Any) -> tuple[tuple[str, int, int], ...]:
    if not isinstance(value, list):
        return ()
    keys = [
        key
        for item in value
        if isinstance(item, dict) and (key := _summary_episode_key(item)) is not None
    ]
    return tuple(dict.fromkeys(keys))


def _nonempty_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _active_records(
    jobs: list[DownloadJob],
) -> dict[tuple[str, int, int], list[dict[str, Any]]]:
    output: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    for job in jobs:
        key = episode_key(job.metadata.values)
        if key is None:
            continue
        output.setdefault(key, []).append(_metadata_record(job.metadata.values))
    return output


def _strict_conflict(
    metadata: ReleaseMetadata,
    records: list[dict[str, Any]],
    planner: ReleaseFilenamePlanner,
) -> bool:
    stem = planner.stem(metadata, include_version=False)
    version = metadata.version or 1
    return any(
        planner.stem(_metadata_from_record(metadata, record), include_version=False)
        == stem
        and version <= int(record.get("version") or 1)
        for record in records
    )


def _metadata_record(metadata: ReleaseMetadata) -> dict[str, Any]:
    return {
        "fansub": metadata.fansub,
        "quality": metadata.quality.value if metadata.quality else "",
        "languages": "".join(item.value for item in metadata.languages),
        "version": metadata.version or 1,
    }


def _metadata_from_record(
    context: ReleaseMetadata, record: dict[str, Any]
) -> ReleaseMetadata:
    quality = record.get("quality")
    language_values = {item.value: item for item in LanguageType}
    return ReleaseMetadata(
        anime_name=context.anime_name,
        season=context.season,
        episode=context.episode,
        fansub=record.get("fansub"),
        quality=VideoQuality(quality) if quality else None,
        languages=[
            language_values[char]
            for char in str(record.get("languages") or "")
            if char in language_values
        ],
        version=int(record.get("version") or 1),
    )


def _episode_label(key: tuple[str, int, int]) -> str:
    return f"{key[0]} S{key[1]:02d}E{key[2]:02d}"


def _inspection_conflict(detail: str) -> ManualPolicyConflict:
    return ManualPolicyConflict(
        key="inspection:incomplete",
        code="policy_inspection_incomplete",
        reason=(
            "Automatic policy inspection was incomplete. If a new RSS policy "
            "conflict is discovered later, the manual task will stop visibly "
            "and require another confirmation."
        ),
        matched=detail,
    )


def _unique_conflicts(
    conflicts: list[ManualPolicyConflict],
) -> tuple[ManualPolicyConflict, ...]:
    unique: dict[str, ManualPolicyConflict] = {}
    for conflict in conflicts:
        unique.setdefault(conflict.key, conflict)
    return tuple(unique.values())


__all__ = [
    "COLLECTION_POLICY_CONFLICT_KEY",
    "MANUAL_PARTIAL_COLLECTION_RETRY_KEY",
    "ManualDownloadPolicyInspector",
    "ManualPartialCollectionRetry",
    "ManualPolicyConflict",
    "ManualPolicyReview",
    "collection_summary_has_retryable_gaps",
    "find_manual_partial_collection_retry",
    "manual_policy_acknowledges",
    "manual_policy_is_approved",
    "manual_partial_collection_retry_from_artifact",
    "matching_metadata_policy_keys",
    "matching_title_policy_keys",
]
