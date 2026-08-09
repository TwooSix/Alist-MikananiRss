"""Pure release filtering, priority and duplicate-selection rules."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .metadata import ReleaseMetadata

EpisodeKey = tuple[str, int, int]

_COLLECTION_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"合集",
        r"全集",
        r"全套",
        r"全\s*[0-9一二三四五六七八九十百两]+\s*(?:集|话|卷|季)",
        r"(?<![\dA-Za-z])\d{1,3}\s*[~–—-]\s*\d{1,3}.*重新打包",
        r"(?:百度网盘|网盘)?打包下载",
        r"(?i)\bcomplete\b",
        r"(?i)(?:[\[(【]\s*(?:official\s+|unofficial\s+|ultimate\s+)?batch\s*[\])】]|[-_/|]\s*(?:official\s+|unofficial\s+|ultimate\s+)?batch\b|\b(?:official|unofficial|ultimate)\s+batch\b)",
        r"\bBATCH\b",
        r"(?i)BD[-\s]*BOX",
        r"(?i)\bTV\s*[+＋]\s*(?:OADs?|OVAs?|Movies?|剧场版)\b",
        r"(?i)\bSeasons\s*\d{1,2}\s*[~–—-]\s*\d{1,2}\b",
        r"(?i)\bS\d{1,2}E\d{1,3}\s*[~–—-]\s*E?\d{1,3}\b",
        r"(?i)\bS(?:eason)?\s*\d{1,2}\s*Complete\b",
        r"(?i)\bEP\s*0?\d{1,3}\s*[~–—-]\s*(?:EP\s*)?0?\d{1,3}\b",
        r"(?i)\b(?:Ep(?:isodes?)?|Eps?)\s*0?\d{1,3}\s*[~–—-]\s*\d{1,3}\b",
        r"(?<![0-9A-Za-z])0\d{1,2}\s*[~–—-]\s*0?\d{1,3}(?!\d)",
        r"[\[【]\s*\d{1,3}\s*[~–—-]\s*\d{1,3}[^]】]*[\]】]",
        r"(?i)(?<![0-9A-Z])\d{1,3}\s*[~–—-]\s*\d{1,3}\s*\+\s*(?:OVA|OAD|SP|Movies?|剧场版)",
        r"(?i)(?<![0-9A-Z])\d{1,3}\s*\+\s*(?:ES|SP|OVA|OAD)\s*0?\d{1,3}\b",
    )
)


def episode_key(metadata: ReleaseMetadata) -> EpisodeKey | None:
    if not metadata.anime_name or metadata.season is None or metadata.episode is None:
        return None
    return metadata.anime_name, metadata.season, metadata.episode


def title_exclusion_reason(title: str, patterns: Iterable[str]) -> str | None:
    for pattern in _COLLECTION_PATTERNS:
        if match := pattern.search(title):
            return match.group(0)
    for raw in patterns:
        if re.search(raw, title):
            return raw
    return None


def metadata_exclusion_reason(
    metadata: ReleaseMetadata,
    *,
    fansubs: Iterable[str],
    qualities: Iterable[str],
    languages: Iterable[str],
) -> str | None:
    fansub_set = set(fansubs)
    quality_set = set(qualities)
    language_set = set(languages)
    if metadata.fansub and metadata.fansub in fansub_set:
        return f"fansub={metadata.fansub}"
    if metadata.quality and metadata.quality.value in quality_set:
        return f"quality={metadata.quality.value}"
    for language in metadata.languages:
        if language.value in language_set:
            return f"language={language.value}"
    return None


def is_version_upgrade(metadata: ReleaseMetadata, records: list[dict]) -> bool:
    languages = "".join(item.value for item in metadata.languages)
    for record in records:
        if (record.get("fansub") or "") != (metadata.fansub or ""):
            continue
        if (record.get("languages") or "") != languages:
            continue
        if (metadata.version or 1) > (record.get("version") or 1):
            return True
    return False


def priority_levels(
    metadata: ReleaseMetadata,
    *,
    field_order: Iterable[str],
    fansubs: list[str],
    qualities: list[str],
    languages: list[str],
) -> tuple[int | None, ...]:
    output: list[int | None] = []
    for field in field_order:
        if field == "fansub" and fansubs:
            output.append(_index(metadata.fansub or "", fansubs))
        elif field == "quality" and qualities:
            output.append(
                _index(metadata.quality.value if metadata.quality else "", qualities)
            )
        elif field == "languages" and languages:
            joined = "".join(sorted(item.value for item in metadata.languages))
            output.append(_language_level(joined, languages))
    return tuple(output)


def dominated_by_records(
    metadata: ReleaseMetadata,
    records: list[dict],
    *,
    field_order: Iterable[str],
    fansubs: list[str],
    qualities: list[str],
    languages: list[str],
) -> bool:
    if not records or is_version_upgrade(metadata, records):
        return False
    candidate = priority_levels(
        metadata,
        field_order=field_order,
        fansubs=fansubs,
        qualities=qualities,
        languages=languages,
    )
    record_levels = [
        _record_priority_levels(
            item,
            field_order=field_order,
            fansubs=fansubs,
            qualities=qualities,
            languages=languages,
        )
        for item in records
    ]
    if not candidate or not record_levels:
        return False
    best = min(record_levels, key=_sort_key)
    return _sort_key(best) < _sort_key(candidate)


def best_indices(levels: list[tuple[int | None, ...]]) -> set[int]:
    if not levels:
        return set()
    best = min(levels, key=_sort_key)
    return {index for index, value in enumerate(levels) if value == best}


def _record_priority_levels(
    record: dict,
    *,
    field_order: Iterable[str],
    fansubs: list[str],
    qualities: list[str],
    languages: list[str],
) -> tuple[int | None, ...]:
    output: list[int | None] = []
    for field in field_order:
        if field == "fansub" and fansubs:
            output.append(_index(record.get("fansub") or "", fansubs))
        elif field == "quality" and qualities:
            output.append(_index(record.get("quality") or "", qualities))
        elif field == "languages" and languages:
            output.append(
                _language_level(
                    "".join(sorted(record.get("languages") or "")), languages
                )
            )
    return tuple(output)


def _index(value: str, values: list[str]) -> int | None:
    try:
        return values.index(value)
    except ValueError:
        return None


def _language_level(value: str, priorities: list[str]) -> int | None:
    normalized = "".join(sorted(value))
    for index, item in enumerate(priorities):
        if "".join(sorted(item)) == normalized:
            return index
    matches = [
        index
        for index, item in enumerate(priorities)
        if len(item) == 1 and item in normalized
    ]
    return min(matches) if matches else None


def _sort_key(levels: tuple[int | None, ...]) -> tuple[float, ...]:
    return tuple(float("inf") if item is None else item for item in levels)
