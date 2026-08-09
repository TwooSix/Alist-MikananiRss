"""Single explicit registry for built-in core adapters."""

from __future__ import annotations

from dataclasses import dataclass, field

from openlist_ani.application.ports import (
    DownloadAdapter,
    FeedAdapter,
    MetadataProvider,
    Organizer,
)


@dataclass(frozen=True)
class DownloadBackendBundle:
    downloader: DownloadAdapter
    organizer: Organizer


@dataclass
class AdapterRegistry:
    feeds: list[FeedAdapter] = field(default_factory=list)
    metadata: dict[str, MetadataProvider] = field(default_factory=dict)
    downloaders: dict[str, DownloadAdapter] = field(default_factory=dict)
    organizers: dict[str, Organizer] = field(default_factory=dict)
    download_backends: dict[str, DownloadBackendBundle] = field(default_factory=dict)

    def register_feed(self, adapter: FeedAdapter) -> None:
        if any(item.name == adapter.name for item in self.feeds):
            raise ValueError(f"Feed adapter already registered: {adapter.name}")
        self.feeds.append(adapter)

    def register_metadata(self, adapter: MetadataProvider) -> None:
        self._put(self.metadata, adapter.name, adapter, "metadata")

    def register_downloader(self, adapter: DownloadAdapter) -> None:
        self._put(self.downloaders, adapter.name, adapter, "downloader")

    def register_organizer(self, name: str, adapter: Organizer) -> None:
        self._put(self.organizers, name, adapter, "organizer")

    def register_download_backend(
        self,
        name: str,
        *,
        downloader: DownloadAdapter,
        organizer: Organizer,
    ) -> None:
        key = name.strip().lower()
        if key in self.download_backends:
            raise ValueError(f"Download backend already registered: {name}")
        self.register_downloader(downloader)
        self.register_organizer(name, organizer)
        self.download_backends[key] = DownloadBackendBundle(downloader, organizer)

    def feed_for(self, url: str) -> FeedAdapter:
        for adapter in self.feeds:
            if adapter.supports(url):
                return adapter
        raise ValueError(f"No feed adapter supports URL: {url}")

    def metadata_pipeline(self, names: tuple[str, ...]) -> list[MetadataProvider]:
        return [self._get(self.metadata, name, "metadata") for name in names]

    def downloader(self, name: str) -> DownloadAdapter:
        return self._get(self.downloaders, name, "downloader")

    def organizer(self, name: str) -> Organizer:
        return self._get(self.organizers, name, "organizer")

    @staticmethod
    def _put(registry: dict, name: str, value: object, kind: str) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError(f"{kind.title()} adapter name cannot be empty")
        if key in registry:
            raise ValueError(f"{kind.title()} adapter already registered: {name}")
        registry[key] = value

    @staticmethod
    def _get(registry: dict, name: str, kind: str):
        key = name.strip().lower()
        try:
            return registry[key]
        except KeyError as exc:
            available = ", ".join(sorted(registry)) or "<none>"
            raise ValueError(
                f"Unknown {kind} adapter '{name}'. Available: {available}"
            ) from exc
