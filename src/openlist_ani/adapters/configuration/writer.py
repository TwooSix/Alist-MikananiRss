"""Comment-preserving, atomic updates for the public TOML file."""

from __future__ import annotations

import os
from pathlib import Path

import tomlkit


def update_rss_urls(path: Path, urls: list[str]) -> None:
    if path.exists():
        document = tomlkit.parse(path.read_text(encoding="utf-8"))
    else:
        document = tomlkit.document()

    rss = document.get("rss")
    if rss is None:
        rss = tomlkit.table()
        document["rss"] = rss
    rss["urls"] = list(urls)

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(tomlkit.dumps(document), encoding="utf-8")
    os.replace(temporary, path)
