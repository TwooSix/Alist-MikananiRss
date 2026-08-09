"""Deterministic, field-level release metadata composition."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from enum import StrEnum
from typing import Any


class VideoQuality(StrEnum):
    Q2160P = "2160p"
    Q1080P = "1080p"
    Q720P = "720p"
    Q480P = "480p"
    Q360P = "360p"
    UNKNOWN = "unknown"


class LanguageType(StrEnum):
    CHS = "简"
    CHT = "繁"
    JP = "日"
    ENG = "英"
    UNKNOWN = "未知"


@dataclass
class ReleaseMetadata:
    anime_name: str | None = None
    season: int | None = None
    episode: int | None = None
    year: int | None = None
    fansub: str | None = None
    quality: VideoQuality | None = None
    languages: list[LanguageType] = field(default_factory=list)
    version: int | None = None
    external_ids: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ReleaseMetadata":
        value = value or {}
        raw_quality = value.get("quality")
        quality = (
            raw_quality
            if isinstance(raw_quality, VideoQuality)
            else VideoQuality(raw_quality) if raw_quality else None
        )
        raw_languages = value.get("languages") or []
        languages = [
            item if isinstance(item, LanguageType) else LanguageType(item)
            for item in raw_languages
        ]
        return cls(
            anime_name=value.get("anime_name"),
            season=value.get("season"),
            episode=value.get("episode"),
            year=value.get("year"),
            fansub=value.get("fansub"),
            quality=quality if quality != VideoQuality.UNKNOWN else None,
            languages=[item for item in languages if item != LanguageType.UNKNOWN],
            version=value.get("version"),
            external_ids={
                str(key): str(item)
                for key, item in (value.get("external_ids") or {}).items()
            },
            extra=dict(value.get("extra") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["quality"] = self.quality.value if self.quality else None
        payload["languages"] = [item.value for item in self.languages]
        return payload

    def minimum_complete(self) -> bool:
        return bool(
            self.anime_name and self.season is not None and self.episode is not None
        )


@dataclass(frozen=True)
class MetadataEvidence:
    source: str
    confidence: float | None = None
    authoritative: bool = False
    degraded: bool = False
    priority: int = 10
    value: Any = None
    previous_value: Any = None
    overrode: bool = False


@dataclass(frozen=True)
class MetadataPatch:
    source: str
    values: ReleaseMetadata
    confidence: float | None = None
    authoritative: bool = False
    degraded: bool = False
    priority: int = 10
    provided_fields: frozenset[str] | None = None


@dataclass
class MetadataDocument:
    values: ReleaseMetadata = field(default_factory=ReleaseMetadata)
    evidence: dict[str, list[MetadataEvidence]] = field(default_factory=dict)

    def apply(self, patch: MetadataPatch) -> None:
        provided = patch.provided_fields or _non_empty_fields(patch.values)
        for name in provided:
            if name not in _METADATA_FIELD_NAMES:
                continue
            incoming = _normalize_field_value(name, getattr(patch.values, name))
            if not _has_value(incoming):
                continue
            existing_evidence = self.evidence.get(name, [])
            existing_value = _normalize_field_value(name, getattr(self.values, name))
            if (
                _has_value(existing_value)
                and existing_evidence
                and existing_evidence[-1].priority > patch.priority
            ):
                continue
            previous = getattr(self.values, name)
            previous_value = _snapshot_value(previous) if _has_value(previous) else None
            if name == "external_ids":
                self.values.external_ids.update(incoming)
            elif name == "extra":
                self.values.extra.update(incoming)
            else:
                setattr(self.values, name, incoming)
            effective_value = _snapshot_value(getattr(self.values, name))
            self.evidence.setdefault(name, []).append(
                MetadataEvidence(
                    source=patch.source,
                    confidence=patch.confidence,
                    authoritative=patch.authoritative,
                    degraded=patch.degraded,
                    priority=patch.priority,
                    value=effective_value,
                    previous_value=previous_value,
                    overrode=(
                        previous_value is not None and previous_value != effective_value
                    ),
                )
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": self.values.to_dict(),
            "evidence": {
                key: [asdict(item) for item in items]
                for key, items in self.evidence.items()
            },
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "MetadataDocument":
        payload = payload or {}
        return cls(
            values=ReleaseMetadata.from_dict(payload.get("values")),
            evidence={
                key: [MetadataEvidence(**item) for item in items]
                for key, items in (payload.get("evidence") or {}).items()
            },
        )


_METADATA_FIELD_NAMES = frozenset(item.name for item in fields(ReleaseMetadata))


def _has_value(value: object) -> bool:
    if value is None or value == "" or value == [] or value == {}:
        return False
    if isinstance(value, VideoQuality) and value == VideoQuality.UNKNOWN:
        return False
    if isinstance(value, LanguageType) and value == LanguageType.UNKNOWN:
        return False
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_has_value(item) for item in value)
    return True


def _normalize_field_value(name: str, value: Any) -> Any:
    if name == "quality" and value == VideoQuality.UNKNOWN:
        return None
    if name == "languages":
        return [item for item in (value or []) if item != LanguageType.UNKNOWN]
    return value


def _snapshot_value(value: Any) -> Any:
    if isinstance(value, (VideoQuality, LanguageType)):
        return value.value
    if isinstance(value, dict):
        return {str(key): _snapshot_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_snapshot_value(item) for item in value]
    return value


def _non_empty_fields(metadata: ReleaseMetadata) -> frozenset[str]:
    return frozenset(
        name
        for name in _METADATA_FIELD_NAMES
        if _has_value(_normalize_field_value(name, getattr(metadata, name)))
    )
