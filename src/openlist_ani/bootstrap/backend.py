"""Backend entry point for the durable modular-monolith runtime."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import aiohttp
import uvicorn

from openlist_ani.adapters.configuration import (
    ConfigValidator,
    compile_core_settings,
    get_config,
    validate_core_settings,
)
from openlist_ani.adapters.download_backends import (
    OpenListDownloadAdapter,
    OpenListOrganizerAdapter,
)
from openlist_ani.adapters.download_backends.openlist import (
    OpenListClient,
    OpenListHealthCheck,
)
from openlist_ani.adapters.feed_sources import (
    AniApiFeedAdapter,
    CommonFeedAdapter,
    MikanFeedAdapter,
)
from openlist_ani.adapters.http.app import create_app
from openlist_ani.adapters.http.service import BackendApiService
from openlist_ani.adapters.metadata_sources import (
    LlmMetadataProvider,
    RegexMetadataProvider,
)
from openlist_ani.adapters.configuration.models import AISourceConfig
from openlist_ani.adapters.metadata_sources.llm.source import create_source_client
from openlist_ani.adapters.metadata_sources.llm import (
    LLMClientSettings,
    create_llm_client,
)
from openlist_ani.adapters.metadata_sources.tmdb import (
    create_tmdb_metadata_provider,
)
from openlist_ani.adapters.metadata_sources.tmdb.settings import (
    MetadataValidatorSettings,
)
from openlist_ani.adapters.notifications import (
    NotificationBotSettings,
    NotificationManagerFactory,
    NotificationSettings,
)
from openlist_ani.adapters.persistence import (
    Database,
    LegacyMigrationRunner,
    SqliteFeedStateRepository,
    SqliteJobRepository,
    SqliteLibraryRepository,
    SqliteMetadataCacheRepository,
    SqliteOutboxRepository,
)
from openlist_ani.adapters.registry import AdapterRegistry
from openlist_ani.application.download_worker import DownloadWorkerPool
from openlist_ani.application.feed_scheduler import FeedScheduler
from openlist_ani.application.metadata_worker import MetadataWorker
from openlist_ani.application.metadata_pipeline import MetadataPipelineResolver
from openlist_ani.application.manual_policy import ManualDownloadPolicyInspector
from openlist_ani.application.notification_worker import NotificationWorker
from openlist_ani.application.ports import DownloadBackendBundle
from openlist_ani.application.service import CoreApplicationService
from openlist_ani.application.settings import CoreSettings
from openlist_ani.bootstrap.runtime import AppRuntime
from openlist_ani.adapters.torrent import (
    LibtorrentUnavailableError,
    TorrentToMagnetCandidateTransformer,
    libtorrent_runtime_version,
    resolve_magnet,
    resolve_torrent,
)
from openlist_ani.logger import FATAL_LEVEL, configure_logger, logger

# Kept as a lazy compatibility hook for integrations that patched the former
# module-level configuration object.  Startup itself always loads explicitly.
config = None


@dataclass(frozen=True)
class _RuntimeAssembly:
    runtime: AppRuntime
    application: CoreApplicationService
    download_backend: DownloadBackendBundle
    download_backends: tuple[DownloadBackendBundle, ...] = ()

    @property
    def openlist_client(self):
        """Compatibility hook for the manual crash-recovery harness."""

        return getattr(self.download_backend.downloader, "_client", None)


async def run() -> None:
    config, core_settings = _load_runtime_config()
    _log_libtorrent_runtime()
    _log_startup_summary(config, core_settings)
    await asyncio.to_thread(LegacyMigrationRunner().run)
    assembly = await _compose_runtime(config, core_settings)

    try:
        await _check_download_backend_health(assembly)
        await assembly.runtime.start()
        BackendApiService.init(assembly.application)
        server = _create_api_server(config)
        logger.info(
            f"Backend API server listening on {config.backend.host}:"
            f"{config.backend.port}"
        )
        try:
            await server.serve()
        except asyncio.CancelledError:
            server.should_exit = True
            raise
    finally:
        logger.info("Shutting down...")
        await assembly.runtime.stop()


def _log_libtorrent_runtime() -> None:
    """Expose native dependency failures at startup instead of first use."""
    try:
        version = libtorrent_runtime_version()
    except LibtorrentUnavailableError as error:
        logger.warning(
            "Magnet metadata resolution is unavailable; other backend features "
            f"will continue to run. {error}"
        )
    else:
        logger.info(f"libtorrent runtime available: version={version}")


def _log_startup_summary(config, core_settings: CoreSettings) -> None:
    """Print the user-facing runtime summary retained from the legacy pipeline."""

    providers = " -> ".join(core_settings.metadata_providers) or "none"
    enabled_bots = sum(1 for bot in config.notification.bots if bot.enabled)
    notification_status = (
        f"enabled ({enabled_bots} target(s))"
        if config.notification.enabled and enabled_bots
        else "disabled"
    )
    logger.info("=" * 56)
    logger.info("OpenList-Ani starting")
    logger.info(f"RSS sources   : {len(config.rss.urls)} configured")
    logger.info(f"Download path : {core_settings.download_path}")
    logger.info(f"Metadata      : {providers}")
    logger.info(f"Downloader    : {core_settings.download_backend}")
    logger.info(f"OpenList URL  : {config.downloader.openlist.url}")
    logger.info(f"Notifications : {notification_status}")
    logger.info(f"Backend API   : {config.backend.host}:{config.backend.port}")
    logger.info("=" * 56)


def _load_runtime_config() -> tuple[object, CoreSettings]:
    config = get_config()
    configure_logger(
        level=config.log.level,
        rotation=config.log.rotation,
        retention=config.log.retention,
        log_name="openlist_ani",
    )
    if config.load_failed:
        logger.log(FATAL_LEVEL, "Configuration could not be parsed; exiting")
        raise SystemExit(1)
    if not ConfigValidator(config.data).validate():
        raise SystemExit(1)
    core_settings = compile_core_settings(config.data)
    validate_core_settings(core_settings)
    return config, core_settings


async def _compose_runtime(config, core_settings: CoreSettings) -> _RuntimeAssembly:
    close_callbacks: list[Callable[[], Awaitable[None]]] = []
    database = Database("data/data.db")
    await database.start()
    close_callbacks.append(database.close)

    feed_session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30),
        trust_env=True,
    )
    close_callbacks.append(feed_session.close)
    try:
        metadata_cache = SqliteMetadataCacheRepository(database)
        registry = _build_registry(
            config,
            core_settings,
            None,
            feed_session,
            metadata_cache,
        )
        for bundle in registry.download_backends.values():
            if bundle.close is not None:
                close_callbacks.append(bundle.close)
        close_callbacks.extend(
            provider.close for provider in registry.metadata.values()
        )
        return await _create_runtime_assembly(
            config,
            core_settings,
            database,
            registry,
            close_callbacks,
        )
    except BaseException:
        await _close_callbacks(close_callbacks)
        raise


async def _create_runtime_assembly(
    config,
    core_settings: CoreSettings,
    database: Database,
    registry: AdapterRegistry,
    close_callbacks: list[Callable[[], Awaitable[None]]],
) -> _RuntimeAssembly:
    download_backend = registry.download_backend(core_settings.download_backend)
    jobs = SqliteJobRepository(
        database,
        downloader_name=download_backend.name,
        lease_seconds=core_settings.job_lease_seconds,
    )
    feeds = SqliteFeedStateRepository(database)
    library = SqliteLibraryRepository(database)
    outbox = SqliteOutboxRepository(
        database,
        lease_seconds=core_settings.job_lease_seconds,
    )
    recovered_jobs = await jobs.recover_interrupted()
    recovered_notifications = await outbox.recover_interrupted()
    if recovered_jobs or recovered_notifications:
        logger.info(
            "Recovered interrupted durable work: "
            f"jobs={recovered_jobs}, notifications={recovered_notifications}"
        )
    metadata_available = asyncio.Event()
    download_available = asyncio.Event()
    notification_available = asyncio.Event()

    scheduler = FeedScheduler(
        registry=registry,
        jobs=jobs,
        feed_state=feeds,
        get_urls=lambda: list(config.rss.urls),
        interval_seconds=core_settings.rss_interval_seconds,
        concurrency=core_settings.feed_concurrency,
        jobs_available=metadata_available,
    )
    metadata_providers = registry.metadata_pipeline(core_settings.metadata_providers)
    metadata_resolver = MetadataPipelineResolver(metadata_providers)
    manual_policy_inspector = ManualDownloadPolicyInspector(
        jobs=jobs,
        library=library,
        metadata_resolver=metadata_resolver,
        settings=core_settings,
    )
    metadata_worker = MetadataWorker(
        jobs=jobs,
        library=library,
        providers=metadata_providers,
        settings=core_settings,
        jobs_available=metadata_available,
        download_available=download_available,
        candidate_transformers=registry.candidate_transformers,
    )
    download_workers = DownloadWorkerPool(
        jobs=jobs,
        backends=registry,
        metadata_resolver=metadata_resolver,
        library=library,
        settings=core_settings,
        work_available=download_available,
        notification_available=notification_available,
    )
    notification_manager = await _create_notification_manager(config)
    if notification_manager is not None:
        close_callbacks.append(notification_manager.stop)
    notification_worker = NotificationWorker(
        outbox=outbox,
        sink=notification_manager,
        available=notification_available,
        batch_interval=config.notification.batch_interval,
    )
    runtime = AppRuntime(
        scheduler=scheduler,
        metadata_worker=metadata_worker,
        download_workers=download_workers,
        notification_worker=notification_worker,
        download_concurrency=core_settings.download_concurrency,
        notification_concurrency=1,
        shutdown_timeout=core_settings.shutdown_timeout_seconds,
        close_callbacks=close_callbacks,
    )
    application = CoreApplicationService(
        jobs=jobs,
        library=library,
        registry=registry,
        settings=core_settings,
        config_manager=config,
        feed_scheduler=scheduler,
        metadata_available=metadata_available,
        resolve_magnet_func=resolve_magnet,
        resolve_torrent_func=resolve_torrent,
        health_provider=runtime.health,
        manual_policy_inspector=manual_policy_inspector,
    )
    return _RuntimeAssembly(
        runtime=runtime,
        application=application,
        download_backend=download_backend,
        download_backends=tuple(registry.download_backends.values()),
    )


async def _check_download_backend_health(assembly: _RuntimeAssembly) -> None:
    bundles = assembly.download_backends or (assembly.download_backend,)
    for bundle in bundles:
        check = bundle.health_check
        if check is None:
            continue
        try:
            healthy = await check()
            if not healthy:
                assembly.runtime.set_degraded(
                    bundle.name,
                    "health check failed; jobs will retry",
                )
                logger.warning(
                    f"Download backend is degraded: {bundle.name}; "
                    "health check failed; jobs will retry"
                )
            else:
                logger.info(f"Download backend ready: {bundle.name}")
        except Exception as error:
            assembly.runtime.set_degraded(bundle.name, str(error))
            logger.warning(
                f"Download backend is degraded: {bundle.name}; error={error}"
            )


async def _close_callbacks(
    callbacks: list[Callable[[], Awaitable[None]]],
) -> None:
    for callback in reversed(callbacks):
        try:
            await callback()
        except Exception as error:
            logger.warning(f"Startup resource close failed: {error}")


def _build_registry(
    config,
    core_settings,
    openlist_client: OpenListClient | None,
    feed_session: aiohttp.ClientSession,
    metadata_cache=None,
) -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register_feed(MikanFeedAdapter(feed_session))
    registry.register_feed(AniApiFeedAdapter(feed_session))
    registry.register_feed(CommonFeedAdapter(feed_session))
    if config.rss.torrent_to_magnet:
        registry.register_candidate_transformer(TorrentToMagnetCandidateTransformer())

    requested_metadata = set(core_settings.metadata_providers)
    if "regex" in requested_metadata:
        registry.register_metadata(RegexMetadataProvider())
    if "ai" in requested_metadata:
        client = _metadata_ai_client(config)
        registry.register_metadata(
            LlmMetadataProvider(
                client,
                disabled_reason=(None if client else "AI source is not configured"),
            )
        )
    if "tmdb" in requested_metadata:
        registry.register_metadata(
            create_tmdb_metadata_provider(
                MetadataValidatorSettings(
                    tmdb_api_key=config.metadata.tmdb.api_key,
                    tmdb_language=config.metadata.tmdb.language,
                ),
                llm_client=_validator_llm_client(
                    config, use_llm="ai" in requested_metadata
                ),
                cache=metadata_cache,
                cache_version=f"4:{config.metadata.tmdb.language}",
                max_concurrency=core_settings.metadata_concurrency,
            )
        )

    registry.register_download_backend(
        _create_openlist_backend_bundle(config, client=openlist_client)
    )
    return registry


def _create_openlist_backend_bundle(
    config,
    *,
    client: OpenListClient | None = None,
) -> DownloadBackendBundle:
    """Own the OpenList client and all lifecycle hooks inside one bundle."""

    client = client or OpenListClient(
        base_url=config.downloader.openlist.url,
        token=config.downloader.openlist.token,
    )
    health = OpenListHealthCheck(
        client=client,
        base_url=config.downloader.openlist.url,
        offline_download_tool=config.downloader.openlist.offline_download_tool,
    )
    close = getattr(client, "close", None)
    return DownloadBackendBundle(
        name="openlist",
        downloader=OpenListDownloadAdapter(
            client=client,
            offline_download_tool=config.downloader.openlist.offline_download_tool,
        ),
        organizer=OpenListOrganizerAdapter(client),
        health_check=health.validate,
        close=close if callable(close) else None,
    )


def _validator_llm_client(config, *, use_llm: bool | None = None):
    if not hasattr(config, "data"):
        if use_llm is None:
            use_llm = config.metadata_parser.provider.strip().lower() == "llm"
        if not use_llm or not config.llm.openai_api_key:
            return None
        return create_llm_client(
            LLMClientSettings(
                provider_type=config.llm.provider_type,
                api_key=config.llm.openai_api_key,
                base_url=config.llm.openai_base_url,
                model=config.llm.openai_model,
            )
        )
    if use_llm is None:
        use_llm = "ai" in config.data.metadata_provider_names()
    if not use_llm:
        return None
    return _metadata_ai_client(config)


def _metadata_ai_client(config):
    selected = config.data.resolve_metadata_ai_source()
    source = (
        selected[1]
        if selected is not None
        else AISourceConfig(type="agent", agent="pi")
    )
    return create_source_client(source)


def _create_validator_llm_client():
    """Compatibility name retained without restoring import-time config loading."""
    if config is None:
        return None
    return _validator_llm_client(config)


async def _create_notification_manager(config):
    manager = NotificationManagerFactory().create(
        NotificationSettings(
            enabled=config.notification.enabled,
            batch_interval=config.notification.batch_interval,
            bots=[
                NotificationBotSettings(
                    type=bot.type,
                    enabled=bot.enabled,
                    config=bot.config_dict(),
                )
                for bot in config.notification.bots
            ],
        )
    )
    if manager is not None:
        try:
            await manager.start()
        except BaseException:
            await manager.stop()
            raise
    return manager


def _create_api_server(config) -> uvicorn.Server:
    return uvicorn.Server(
        uvicorn.Config(
            create_app(),
            host=config.backend.host,
            port=config.backend.port,
            log_level="warning",
        )
    )


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Interrupted by user.")
    except SystemExit:
        raise
    except Exception as error:
        logger.log(FATAL_LEVEL, f"Backend terminated unexpectedly: {error}")
        sys.exit(1)
