from __future__ import annotations

from dataclasses import dataclass

import pytest

from openlist_ani.adapters.registry import AdapterRegistry
from openlist_ani.application.ports import DownloadBackendBundle


@dataclass(frozen=True)
class _Downloader:
    name: str


@dataclass(frozen=True)
class _Organizer:
    backend_name: str


def _bundle(
    name: str,
    *,
    downloader_name: str | None = None,
    organizer_name: str | None = None,
) -> DownloadBackendBundle:
    return DownloadBackendBundle(
        name=name,
        downloader=_Downloader(downloader_name or name.strip().lower()),
        organizer=_Organizer(organizer_name or name.strip().lower()),
    )


def test_download_backend_registration_returns_one_bound_bundle():
    registry = AdapterRegistry()
    downloader = _Downloader("openlist")
    organizer = _Organizer("openlist")

    registry.register_download_backend(
        DownloadBackendBundle(
            name=" OpenList ",
            downloader=downloader,
            organizer=organizer,
        )
    )

    bundle = registry.download_backend("OPENLIST")
    assert isinstance(bundle, DownloadBackendBundle)
    assert bundle.name == "openlist"
    assert bundle.downloader is downloader
    assert bundle.organizer is organizer
    assert not hasattr(registry, "downloaders")
    assert not hasattr(registry, "organizers")


def test_download_backend_registration_preserves_lifecycle_callbacks():
    async def health_check() -> bool:
        return True

    async def close() -> None:
        return None

    registry = AdapterRegistry()
    registry.register_download_backend(
        DownloadBackendBundle(
            name="openlist",
            downloader=_Downloader("openlist"),
            organizer=_Organizer("openlist"),
            health_check=health_check,
            close=close,
        )
    )

    bundle = registry.download_backend("openlist")
    assert bundle.health_check is health_check
    assert bundle.close is close


@pytest.mark.parametrize(
    ("downloader_name", "organizer_name", "message"),
    [
        ("local", "openlist", "Downloader backend name does not match bundle"),
        ("openlist", "local", "Organizer backend name does not match bundle"),
    ],
)
def test_download_backend_registration_rejects_cross_backend_pairing_atomically(
    downloader_name: str,
    organizer_name: str,
    message: str,
):
    registry = AdapterRegistry()
    bundle = _bundle(
        "openlist",
        downloader_name=downloader_name,
        organizer_name=organizer_name,
    )

    with pytest.raises(ValueError, match=message):
        registry.register_download_backend(bundle)

    assert registry.download_backends == {}


def test_download_backend_duplicate_does_not_replace_registered_bundle():
    registry = AdapterRegistry()
    first_downloader = _Downloader("openlist")
    first_organizer = _Organizer("openlist")
    registry.register_download_backend(
        DownloadBackendBundle(
            name="openlist",
            downloader=first_downloader,
            organizer=first_organizer,
        )
    )

    duplicate = _bundle("OPENLIST")
    with pytest.raises(ValueError, match="already registered"):
        registry.register_download_backend(duplicate)

    bundle = registry.download_backend("openlist")
    assert bundle.downloader is first_downloader
    assert bundle.organizer is first_organizer


def test_unknown_download_backend_lists_available_backends():
    registry = AdapterRegistry()
    registry.register_download_backend(_bundle("openlist"))

    with pytest.raises(
        ValueError,
        match="Unknown download backend adapter 'local'.*openlist",
    ):
        registry.download_backend("local")
