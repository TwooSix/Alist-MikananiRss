"""Pure collection inventory, episode-context and subtitle matching rules."""

from __future__ import annotations

import hashlib
import posixpath
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from openlist_ani.application.ports import (
    DownloadManifest,
    DownloadedFile,
    OrganizationSidecar,
)
from openlist_ani.domain import ReleaseMetadata

VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".mpg", ".mpeg"}
)
SUBTITLE_EXTENSIONS = frozenset(
    {".ass", ".ssa", ".srt", ".vtt", ".sub", ".idx", ".sup"}
)

_ASCII_EXTRA_SUFFIX = re.compile(
    r"(?ix)(?:^|[\s._\-\[\]()])"
    r"(?:specials?|ova|oad|n?cop|n?ced|pv|cm|trailer|sample|extras?|sp|op|ed)"
    r"\s*\d{0,3}"
    r"(?:\s*(?:v\d+|(?:720|1080|2160)p|\[[^\]]+\]|\([^)]*\)))*\s*$"
)
_EXTRA_DIRECTORY = re.compile(
    r"(?ix)^(?:ovas?|oads?|sps?|n?cops?|n?ceds?|ops?|eds?|pvs?|cms?|"
    r"trailers?|samples?|specials?|extras?|bonuses?)"
    r"(?:[\s._-]+(?:collection|disc|bonus|extras?))?$"
)
_CJK_EXTRA_TOKEN = re.compile(
    r"特典|映像特典|花絮|预告|預告|宣传片|宣傳片|片头|片尾|片頭"
)
_SEASON_SEGMENT = re.compile(
    r"(?i)(?:^|[^a-z0-9])(?:season\s*|s)(?P<season>\d{1,2})(?:$|[^a-z0-9])"
)
_CHINESE_SEASON_SEGMENT = re.compile(
    r"第\s*(?P<season>[一二两三四五六七八九十百\d]{1,3})\s*[季期部]"
)
_BRACKET_TAG = re.compile(r"\[[^\]]+\]|【[^】]+】|\([^()]+\)")
_SPARSE_EPISODE_TEXT = re.compile(
    r"(?i)^(?:e|ep(?:isode)?)?[ ._-]*(?P<episode>\d{1,3})"
    r"(?P<suffix>(?:[ ._-]*(?:v\d+|2160p|1080p|720p|480p|360p|4k|"
    r"chs|cht|jpn|eng))*)$"
)
_COMPACT_EPISODE_TAG = re.compile(
    r"(?i)^(?:e|ep(?:isode)?)?\s*(?P<episode>\d{1,3})(?:\s*(?P<version>v\d+))?$"
)
_SEASON_TITLE_TOKEN = re.compile(r"(?i)\b(?:season\s*|s)\d{1,2}\b(?!\s*e\d)")
_FIRST_EPISODE_REPLACEMENT = r" - \g<first>"
_COLLECTION_RANGE_REPLACEMENTS = (
    (
        re.compile(r"(?i)\b(S\d{1,2}E\d{1,3})\s*[-~–—～]\s*E?\d{1,3}\b"),
        r"\1",
    ),
    (
        re.compile(r"(?i)\b(EP\s*0?\d{1,3})\s*[-~–—～]\s*(?:EP\s*)?0?\d{1,3}\b"),
        r"\1",
    ),
    (
        re.compile(r"(?i)\bE(?P<first>0?\d{1,3})\s*[-~–—～]\s*E?0?\d{1,3}\b"),
        _FIRST_EPISODE_REPLACEMENT,
    ),
    (
        re.compile(r"[\[【]\s*(?P<first>0?\d{1,3})\s*[-~–—～]\s*0?\d{1,3}\s*[\]】]"),
        _FIRST_EPISODE_REPLACEMENT,
    ),
    (
        re.compile(
            r"(?<![A-Za-z0-9])(?P<first>0?\d{1,3})\s*[-~–—～]\s*0?\d{1,3}(?!\d)"
        ),
        _FIRST_EPISODE_REPLACEMENT,
    ),
)
_COLLECTION_WORDS = re.compile(
    r"(?i)(?:合集|全集|全套|全\s*\d+\s*[集话話]|complete|bd[-\s]*box|重新打包)"
)
_TRAILING_BATCH_MARKER = re.compile(
    r"(?ix)(?:\[(?:official\s+|unofficial\s+|ultimate\s+)?batch\]|"
    r"\((?:official\s+|unofficial\s+|ultimate\s+)?batch\)|"
    r"(?:official\s+|unofficial\s+|ultimate\s+)?batch"
    r"(?=\s*(?:\[[^\]]+\]|\([^)]*\))*\s*$))"
)
_PARENT_EPISODE_HINT = re.compile(
    r"(?i)(?:\bS\d{1,2}E\d{1,3}\b|\bEP(?:ISODE)?\s*\d{1,3}\b|"
    r"\s[-–—]\s*\d{1,3}(?:\D|$)|(?<!\d)\d{1,3}\s*$|"
    r"[\[【]\s*\d{1,3}(?:\s*v\d+)?\s*[\]】])"
)
_PREFIX_BOUNDARY = frozenset(" ._-[](){}（）【】")


@dataclass(frozen=True)
class CollectionVideo:
    """A video leaf plus the subtitles deterministically assigned to it."""

    relative_path: str
    size: int
    item_key: str
    sidecars: tuple[OrganizationSidecar, ...] = ()


def normalize_relative_path(value: str) -> str:
    """Return a backend-neutral relative POSIX path and reject traversal."""

    raw = value.replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        raise ValueError(f"Invalid manifest relative path: {value!r}")
    normalized = posixpath.normpath(raw)
    if normalized in {"", "."} or normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"Invalid manifest relative path: {value!r}")
    return normalized


def stable_item_key(relative_path: str) -> str:
    normalized = normalize_relative_path(relative_path)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def collection_videos(manifest: DownloadManifest) -> tuple[CollectionVideo, ...]:
    """Select every video and bind each subtitle to at most one video."""

    files = tuple(_normalize_file(item) for item in manifest.files)
    videos = tuple(
        item
        for item in files
        if PurePosixPath(item.relative_path).suffix.lower() in VIDEO_EXTENSIONS
    )
    subtitles = tuple(
        item
        for item in files
        if PurePosixPath(item.relative_path).suffix.lower() in SUBTITLE_EXTENSIONS
    )
    assigned = _bind_subtitles(videos, subtitles)
    return tuple(
        CollectionVideo(
            relative_path=video.relative_path,
            size=video.size,
            item_key=stable_item_key(video.relative_path),
            sidecars=assigned.get(video.relative_path, ()),
        )
        for video in sorted(videos, key=lambda item: item.relative_path.casefold())
    )


def is_main_feature_path(relative_path: str) -> bool:
    """Reject files visibly classified as specials, promos or bonus material."""

    path = PurePosixPath(normalize_relative_path(relative_path))
    for index, part in enumerate(path.parts):
        # Directory names may legitimately contain dots (for example
        # ``Takt Op. Destiny``), so only strip the extension from the leaf.
        is_leaf = index == len(path.parts) - 1
        text = PurePosixPath(part).stem if is_leaf else part
        if (
            (not is_leaf and _is_extra_directory(text))
            or _CJK_EXTRA_TOKEN.search(text)
            or (is_leaf and _ASCII_EXTRA_SUFFIX.search(text))
        ):
            return False
    return True


def explicit_path_season(relative_path: str) -> int | None:
    """Read an explicit season from directories; nearest directory wins."""

    directories = PurePosixPath(normalize_relative_path(relative_path)).parts[:-1]
    for segment in reversed(directories):
        if match := _SEASON_SEGMENT.search(segment):
            return int(match.group("season"))
        if match := _CHINESE_SEASON_SEGMENT.search(segment):
            return _chinese_integer(match.group("season"))
    return None


def collection_parent_probe(title: str) -> str:
    """Turn a range/batch title into a parseable representative title."""

    value = title
    for pattern, replacement in _COLLECTION_RANGE_REPLACEMENTS:
        value = pattern.sub(replacement, value)
    # Detect a trailing Batch marker against the original marker context.
    # Doing this after removing "Complete" would corrupt real titles such as
    # "The Bad Batch Complete" by making the title word look newly trailing.
    value = _TRAILING_BATCH_MARKER.sub(" ", value)
    value = _COLLECTION_WORDS.sub(" ", value)
    value = re.sub(r"\s+", " ", value).strip(" -_")
    episode_probe = _SEASON_TITLE_TOKEN.sub(" ", value)
    if value and not _PARENT_EPISODE_HINT.search(episode_probe):
        value = f"{value} - 01"
    return value


def child_release_title(relative_path: str, parent: ReleaseMetadata) -> str:
    """Build the per-file parser input without deriving episodes from ordering."""

    path = PurePosixPath(normalize_relative_path(relative_path))
    stem = path.stem.strip()
    explicit_season = explicit_path_season(relative_path)
    season = explicit_season if explicit_season is not None else parent.season
    anime_name = parent.anime_name or _directory_anime_hint(path)
    sparse_episode = _sparse_episode_parts(stem)
    if sparse_episode and anime_name:
        season_text = f"S{season:02d}" if season is not None else "S01"
        leading_tags, episode_text = sparse_episode
        prefix = f"{leading_tags} " if leading_tags else ""
        return f"{prefix}{anime_name} {season_text} - {episode_text}".strip()

    # Full filenames remain authoritative.  Directory names are useful context
    # only when the leaf itself does not already identify the series.
    if anime_name and not _looks_like_full_release(stem, anime_name):
        season_text = f"S{season:02d}" if season is not None else "S01"
        return f"{anime_name} {season_text} - {stem}"
    return stem


def parent_context(metadata: ReleaseMetadata) -> ReleaseMetadata:
    """Copy only fields that may safely flow from a parent collection."""

    return ReleaseMetadata(
        anime_name=metadata.anime_name,
        season=metadata.season,
        episode=None,
        fansub=metadata.fansub,
        quality=metadata.quality,
        languages=list(metadata.languages),
        external_ids=dict(metadata.external_ids),
    )


def _normalize_file(item: DownloadedFile) -> DownloadedFile:
    return DownloadedFile(
        relative_path=normalize_relative_path(item.relative_path),
        size=max(0, int(item.size)),
    )


def _bind_subtitles(
    videos: tuple[DownloadedFile, ...], subtitles: tuple[DownloadedFile, ...]
) -> dict[str, tuple[OrganizationSidecar, ...]]:
    assigned: dict[str, list[OrganizationSidecar]] = {
        item.relative_path: [] for item in videos
    }
    for subtitle in sorted(subtitles, key=lambda item: item.relative_path.casefold()):
        candidates = _subtitle_candidates(subtitle, videos)
        if len(candidates) != 1:
            continue
        video, suffix = candidates[0]
        assigned[video.relative_path].append(
            OrganizationSidecar(relative_path=subtitle.relative_path, suffix=suffix)
        )
    return {
        path: tuple(sorted(items, key=lambda item: item.relative_path.casefold()))
        for path, items in assigned.items()
    }


def _subtitle_candidates(
    subtitle: DownloadedFile, videos: tuple[DownloadedFile, ...]
) -> list[tuple[DownloadedFile, str]]:
    subtitle_path = PurePosixPath(subtitle.relative_path)
    same_directory = [
        video
        for video in videos
        if PurePosixPath(video.relative_path).parent == subtitle_path.parent
    ]
    local = _stem_matches(subtitle_path.stem, same_directory)
    if local:
        return local

    # A subtitle detached from its video directory is safe only when its stem
    # identifies one video across the entire collection.
    remote = _stem_matches(subtitle_path.stem, list(videos))
    return remote if len(remote) == 1 else []


def _stem_matches(
    subtitle_stem: str, videos: list[DownloadedFile]
) -> list[tuple[DownloadedFile, str]]:
    exact: list[tuple[DownloadedFile, str]] = []
    prefix: list[tuple[int, DownloadedFile, str]] = []
    folded_subtitle = subtitle_stem.casefold()
    for video in videos:
        video_stem = PurePosixPath(video.relative_path).stem
        folded_video = video_stem.casefold()
        if folded_subtitle == folded_video:
            exact.append((video, ""))
            continue
        if not folded_subtitle.startswith(folded_video):
            continue
        remainder = subtitle_stem[len(video_stem) :]
        if remainder and remainder[0] in _PREFIX_BOUNDARY:
            prefix.append((len(video_stem), video, remainder))
    if exact:
        return exact
    if not prefix:
        return []
    longest = max(item[0] for item in prefix)
    return [(video, suffix) for length, video, suffix in prefix if length == longest]


def _looks_like_full_release(stem: str, anime_name: str) -> bool:
    folded = stem.casefold()
    if anime_name.casefold() in folded:
        return True
    return bool(
        re.search(r"(?i)\bS\d{1,2}E\d{1,3}\b", stem)
        or re.search(r"[A-Za-z\u3400-\u9fff\u3040-\u30ff]{2,}", stem)
    )


def _leading_bracket_episode(
    stem: str,
) -> tuple[int, list[str], tuple[str, str] | None]:
    cursor = 0
    tags: list[str] = []
    while cursor < len(stem):
        whitespace = re.match(r"\s*", stem[cursor:])
        start = cursor + (whitespace.end() if whitespace else 0)
        match = _BRACKET_TAG.match(stem, start)
        if match is None:
            break
        content = match.group(0)[1:-1].strip()
        compact = _COMPACT_EPISODE_TAG.fullmatch(content)
        if compact is not None:
            version = f" {compact.group('version')}" if compact.group("version") else ""
            tail = stem[match.end() :].strip()
            episode_text = f"{compact.group('episode')}{version}"
            if tail:
                episode_text = f"{episode_text} {tail}"
            return match.end(), tags, (" ".join(tags), episode_text)
        tags.append(match.group(0))
        cursor = match.end()

    return cursor, tags, None


def _sparse_episode_parts(stem: str) -> tuple[str, str] | None:
    """Return leading group tags and a canonical episode-plus-metadata suffix."""

    cursor, tags, bracket_episode = _leading_bracket_episode(stem)
    if bracket_episode is not None:
        return bracket_episode

    body = stem[cursor:].strip()
    bracket_suffix = " ".join(match.group(0) for match in _BRACKET_TAG.finditer(body))
    normalized = re.sub(r"\s+", " ", _BRACKET_TAG.sub(" ", body)).strip()
    match = _SPARSE_EPISODE_TEXT.fullmatch(normalized)
    if match is None:
        return None
    suffix = match.group("suffix").strip(" ._-")
    episode_text = match.group("episode")
    if suffix:
        episode_text = f"{episode_text} {suffix}"
    if bracket_suffix:
        episode_text = f"{episode_text} {bracket_suffix}"
    return " ".join(tags), episode_text


def _directory_anime_hint(path: PurePosixPath) -> str | None:
    ignored = re.compile(
        r"(?i)^(?:s\d{1,2}|season\s*\d{1,2}|disc\s*\d+|cd\s*\d+|"
        r"videos?|episodes?|downloads?|bdmv|complete|batch|合集|全集)$"
    )
    # The outermost meaningful directory usually identifies the series;
    # inner directories often describe discs, cours or arbitrary parts.
    for segment in path.parts[:-1]:
        value = segment.strip()
        if not value or ignored.fullmatch(value):
            continue
        if _CHINESE_SEASON_SEGMENT.search(value) or _SEASON_SEGMENT.search(value):
            continue
        return value
    return None


def _is_extra_directory(value: str) -> bool:
    normalized = value.strip()
    while True:
        without_tag = _without_trailing_directory_tag(normalized)
        if without_tag == normalized:
            break
        normalized = without_tag
    if len(normalized) >= 2 and (normalized[0], normalized[-1]) in {
        ("[", "]"),
        ("【", "】"),
        ("(", ")"),
    }:
        normalized = normalized[1:-1].strip()
    return bool(_EXTRA_DIRECTORY.fullmatch(normalized))


def _without_trailing_directory_tag(value: str) -> str:
    closing = value[-1:]
    opening = {"]": "[", "】": "【", ")": "("}.get(closing)
    if opening is None:
        return value

    for index in range(1, len(value) - 1):
        if value[index] != opening or not value[index - 1].isspace():
            continue
        content = value[index + 1 : -1]
        if not content or closing in content:
            continue
        if closing == ")" and "(" in content:
            continue
        return value[:index].rstrip()
    return value


def _chinese_integer(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value == "十":
        return 10
    if "十" in value:
        left, _, right = value.partition("十")
        return digits.get(left, 1) * 10 + digits.get(right, 0)
    return digits.get(value)


__all__ = [
    "CollectionVideo",
    "SUBTITLE_EXTENSIONS",
    "VIDEO_EXTENSIONS",
    "child_release_title",
    "collection_parent_probe",
    "collection_videos",
    "explicit_path_season",
    "is_main_feature_path",
    "normalize_relative_path",
    "parent_context",
    "stable_item_key",
]
