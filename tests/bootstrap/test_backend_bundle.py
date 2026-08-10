from openlist_ani.adapters.configuration import compile_core_settings
from openlist_ani.adapters.configuration.models import UserConfig
from openlist_ani.adapters.download_backends import (
    OpenListDownloadAdapter,
    OpenListOrganizerAdapter,
)
from openlist_ani.bootstrap.backend import _build_registry


def test_bootstrap_registers_openlist_as_one_bound_download_backend():
    config = UserConfig.model_validate({"metadata": {"pipeline": ["regex"]}})
    settings = compile_core_settings(config)
    openlist_client = object()

    registry = _build_registry(
        config,
        settings,
        openlist_client,
        feed_session=object(),
    )

    bundle = registry.download_backend(settings.download_backend)
    assert bundle.name == "openlist"
    assert isinstance(bundle.downloader, OpenListDownloadAdapter)
    assert isinstance(bundle.organizer, OpenListOrganizerAdapter)
    assert bundle.downloader._client is openlist_client
    assert bundle.organizer._client is openlist_client
