"""Durable, bounded-window notification batch coordinator."""

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
        batch_interval: float = 300.0,
    ) -> None:
        self._outbox = outbox
        self._sink = sink
        self._available = available
        self._batch_interval = max(0.0, batch_interval)
        self._stop = asyncio.Event()

    async def stop(self) -> None:
        self._stop.set()
        self._available.set()

    async def run(self, worker_id: int = 0) -> None:
        while not self._stop.is_set():
            try:
                targets = self._sink.targets() if self._sink is not None else ()
                target_keys = tuple(target.key for target in targets)
                await self._outbox.initialize_targets(target_keys)

                delivered = False
                if self._sink is not None:
                    results = await asyncio.gather(
                        *(self._deliver_target(target.key) for target in targets),
                        return_exceptions=True,
                    )
                    for result in results:
                        if isinstance(result, BaseException):
                            logger.warning(
                                f"Notification target worker recovered: {result}"
                            )
                        else:
                            delivered = delivered or result
                if delivered:
                    continue

                delay = await self._outbox.next_due_delay(
                    target_keys, self._batch_interval
                )
                await self._wait(delay)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning(
                    f"Notification worker recovered: worker={worker_id}; error={error}"
                )
                await self._wait(5.0)

    async def _deliver_target(self, target_key: str) -> bool:
        assert self._sink is not None
        items = await self._outbox.claim_due(target_key, self._batch_interval)
        if not items:
            return False
        try:
            batches = self._sink.format_download_batches(target_key, items)
        except Exception as error:
            await self._outbox.delivery_retry(items, str(error))
            return False

        included_ids = {item.id for batch in batches for item in batch.items}
        missing = [item for item in items if item.id not in included_ids]
        if missing:
            await self._outbox.delivery_retry(
                missing, "notification formatter omitted claimed items"
            )

        for batch in batches:
            batch_items = list(batch.items)
            try:
                success = await self._sink.send_to_target(
                    target_key, batch.message
                )
            except Exception as error:
                await self._outbox.delivery_retry(batch_items, str(error))
                continue
            if success:
                await self._outbox.delivery_succeeded(batch_items)
            else:
                await self._outbox.delivery_retry(
                    batch_items, "notification target failed after retries"
                )
        return True

    async def _wait(self, delay: float | None) -> None:
        self._available.clear()
        if self._stop.is_set():
            return
        timeout = 5.0 if delay is None else min(5.0, max(0.01, delay))
        try:
            await asyncio.wait_for(self._available.wait(), timeout=timeout)
        except TimeoutError:
            pass
