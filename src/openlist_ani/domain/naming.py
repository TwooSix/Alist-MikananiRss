"""Pure directory and filename planning rules."""

from __future__ import annotations

import os
import re

from .metadata import ReleaseMetadata


def sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*]', " ", name).strip()
    # A metadata-derived directory component must never be able to resolve to
    # the current or parent directory.  Empty names receive the same stable
    # fallback used by the naming planners.
    return "Unknown" if sanitized in {"", ".", ".."} else sanitized


def format_anime_episode(
    anime_name: str | None, season: int | None, episode: int | None
) -> str:
    name = anime_name or "Unknown"
    season_text = f"S{season:02d}" if season is not None else "S??"
    episode_text = f"E{episode:02d}" if episode is not None else "E??"
    return f"{name} {season_text}{episode_text}"


def format_release_stem(
    rename_format: str,
    metadata: ReleaseMetadata,
    *,
    include_version: bool = True,
) -> str:
    context = {
        "anime_name": sanitize_filename(metadata.anime_name or "Unknown"),
        "season": metadata.season or 1,
        "episode": metadata.episode or 1,
        "year": metadata.year or "",
        "fansub": metadata.fansub or "",
        "quality": str(metadata.quality) if metadata.quality else "",
        "languages": "".join(str(item) for item in metadata.languages),
    }
    try:
        stem = rename_format.format(**context).strip()
    except (KeyError, ValueError, IndexError, TypeError):
        stem = (
            f"{context['anime_name']} "
            f"S{context['season']:02d}E{context['episode']:02d}"
        )
    version = metadata.version or 1
    return f"{stem} v{version}" if include_version and version > 1 else stem


class ReleaseFilenamePlanner:
    def __init__(self, rename_format: str) -> None:
        self._rename_format = rename_format

    def filename(self, metadata: ReleaseMetadata, source_filename: str) -> str:
        extension = os.path.splitext(source_filename)[1] or ".mp4"
        return f"{self.stem(metadata)}{extension}".strip()

    def stem(self, metadata: ReleaseMetadata, *, include_version: bool = True) -> str:
        return format_release_stem(
            self._rename_format,
            metadata,
            include_version=include_version,
        )


class ReleaseDirectoryPlanner:
    def target_directory_path(self, base_path: str, metadata: ReleaseMetadata) -> str:
        anime_name = sanitize_filename(metadata.anime_name or "Unknown")
        return f"{base_path.rstrip('/')}/{anime_name}/Season {metadata.season or 1}"
