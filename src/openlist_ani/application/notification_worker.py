"""Best-effort delivery backed by a durable outbox."""

from __future__ import annotations

import asyncio

from openlist_ani.application.ports import NotificationSink, OutboxRepository
from openlist_ani.logger import logger


class NotificationWorker:
    def __init__(
        self,
        *,
        outbox: OutboxRepository,
        sink: NotificationSink | None,
        available: asyncio.Event,
    ) -> None:
        self._outbox = outbox
        self._sink = sink
        self._available = available
        self._stop = asyncio.Event()

    async def stop(self) -> None:
        self._stop.set()
        self._available.set()

    async def run(self, worker_id: int) -> None:
        while not self._stop.is_set():
            item = None
            try:
                items = await self._outbox.claim(1)
                if not items:
                    await self._wait()
                    continue
                item = items[0]
                if self._sink is None:
                    await self._outbox.delivered(item)
                    continue
                result = await self._sink.send_download_complete_notification(
                    item.anime_name, item.title
                )
                if result and not all(result.values()):
                    raise RuntimeError("one or more notification targets failed")
                await self._outbox.delivered(item)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if item is not None:
                    try:
                        await self._outbox.retry(item, str(error))
                    except Exception as retry_error:
                        logger.warning(
                            f"Notification retry persistence failed: {retry_error}"
                        )
                logger.warning(
                    f"Notification worker recovered: worker={worker_id}; error={error}"
                )
                await self._wait()

    async def _wait(self) -> None:
        self._available.clear()
        try:
            await asyncio.wait_for(self._available.wait(), timeout=5.0)
        except TimeoutError:
            pass
