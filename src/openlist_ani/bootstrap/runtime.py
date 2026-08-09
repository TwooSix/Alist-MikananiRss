"""Owned lifecycle for the durable core workers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from openlist_ani.logger import logger


class AppRuntime:
    def __init__(
        self,
        *,
        scheduler,
        metadata_worker,
        download_workers,
        notification_worker,
        download_concurrency: int,
        notification_concurrency: int,
        shutdown_timeout: float = 30.0,
        close_callbacks: list[Callable[[], Awaitable[None]]] | None = None,
    ) -> None:
        self.scheduler = scheduler
        self.metadata_worker = metadata_worker
        self.download_workers = download_workers
        self.notification_worker = notification_worker
        self._download_concurrency = max(1, download_concurrency)
        self._notification_concurrency = max(1, notification_concurrency)
        self._shutdown_timeout = shutdown_timeout
        self._close_callbacks = close_callbacks or []
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False
        self._resources_closed = False
        self._degraded: dict[str, str] = {}

    async def start(self) -> None:  # NOSONAR - awaitable lifecycle contract
        if self._resources_closed:
            raise RuntimeError("Cannot restart a closed runtime")
        if self._running:
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self.scheduler.run(), name="feed-scheduler"),
            asyncio.create_task(self.metadata_worker.run(), name="metadata-worker"),
            *[
                asyncio.create_task(
                    self.download_workers.run(index),
                    name=f"download-worker-{index}",
                )
                for index in range(self._download_concurrency)
            ],
            *[
                asyncio.create_task(
                    self.notification_worker.run(index),
                    name=f"notification-worker-{index}",
                )
                for index in range(self._notification_concurrency)
            ],
        ]
        for task in self._tasks:
            task.add_done_callback(self._worker_finished)
        logger.info(
            "Durable core runtime started: "
            f"downloads={self._download_concurrency}, "
            f"notifications={self._notification_concurrency}"
        )

    async def stop(self) -> None:
        if self._resources_closed:
            return
        if self._running:
            self._running = False
            await asyncio.gather(
                self.scheduler.stop(),
                self.metadata_worker.stop(),
                self.download_workers.stop(),
                self.notification_worker.stop(),
            )
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._tasks, return_exceptions=True),
                    timeout=self._shutdown_timeout,
                )
            except TimeoutError:
                for task in self._tasks:
                    task.cancel()
                await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        for callback in reversed(self._close_callbacks):
            try:
                await callback()
            except Exception as error:
                logger.warning(f"Runtime resource close failed: {error}")
        self._resources_closed = True
        logger.info("Durable core runtime stopped")

    def set_degraded(self, component: str, reason: str) -> None:
        self._degraded[component] = reason

    def health(self) -> dict[str, object]:
        running = sum(1 for task in self._tasks if not task.done())
        expected = len(self._tasks)
        ready = self._running and running == expected
        degraded = dict(self._degraded)
        if self._running and running != expected:
            degraded["workers"] = f"running={running}, expected={expected}"
        health_status = "not_ready"
        if degraded:
            health_status = "degraded"
        elif ready:
            health_status = "ready"
        return {
            "status": health_status,
            "ready": ready,
            "degraded": degraded,
            "workers": {
                "running": running,
                "expected": expected,
            },
        }

    def _worker_finished(self, task: asyncio.Task[None]) -> None:
        if not self._running or task.cancelled():
            return
        error = task.exception()
        reason = str(error) if error else "worker exited unexpectedly"
        self._degraded[task.get_name()] = reason
        logger.error(f"Runtime worker stopped: name={task.get_name()}; error={reason}")
