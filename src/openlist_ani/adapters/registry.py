"""Single explicit registry for built-in core adapters."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from openlist_ani.application.ports import (
    CandidateTransformer,
    DownloadBackendBundle,
    FeedAdapter,
    MetadataProvider,
)


@dataclass
class AdapterRegistry:
    feeds: list[FeedAdapter] = field(default_factory=list)
    metadata: dict[str, MetadataProvider] = field(default_factory=dict)
    candidate_transformers: list[CandidateTransformer] = field(default_factory=list)
    download_backends: dict[str, DownloadBackendBundle] = field(default_factory=dict)

    def register_feed(self, adapter: FeedAdapter) -> None:
        if any(item.name == adapter.name for item in self.feeds):
            raise ValueError(f"Feed adapter already registered: {adapter.name}")
        self.feeds.append(adapter)

    def register_metadata(self, adapter: MetadataProvider) -> None:
        self._put(self.metadata, adapter.name, adapter, "metadata")

    def register_candidate_transformer(self, adapter: CandidateTransformer) -> None:
        if any(item.name == adapter.name for item in self.candidate_transformers):
            raise ValueError(
                f"Candidate transformer already registered: {adapter.name}"
            )
        self.candidate_transformers.append(adapter)

    def register_download_backend(self, bundle: DownloadBackendBundle) -> None:
        key = bundle.name.strip().lower()
        if not key:
            raise ValueError("Download backend name cannot be empty")
        if key in self.download_backends:
            raise ValueError(f"Download backend already registered: {bundle.name}")
        downloader_name = bundle.downloader.name.strip().lower()
        organizer_name = bundle.organizer.backend_name.strip().lower()
        if downloader_name != key:
            raise ValueError(
                "Downloader backend name does not match bundle: "
                f"{bundle.downloader.name} != {key}"
            )
        if organizer_name != key:
            raise ValueError(
                "Organizer backend name does not match bundle: "
                f"{bundle.organizer.backend_name} != {key}"
            )
        self.download_backends[key] = replace(bundle, name=key)

    def feed_for(self, url: str) -> FeedAdapter:
        for adapter in self.feeds:
            if adapter.supports(url):
                return adapter
        raise ValueError(f"No feed adapter supports URL: {url}")

    def metadata_pipeline(self, names: tuple[str, ...]) -> list[MetadataProvider]:
        return [self._get(self.metadata, name, "metadata") for name in names]

    def download_backend(self, name: str) -> DownloadBackendBundle:
        return self._get(self.download_backends, name, "download backend")

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
