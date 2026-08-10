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

    async def stop(self) -> None:  # NOSONAR - awaitable lifecycle contract
        self._stop.set()
        self._available.set()

    async def run(self, worker_id: int = 0) -> None:
        announced_targets: tuple[str, ...] | None = None
        while not self._stop.is_set():
            try:
                targets = self._sink.targets() if self._sink is not None else ()
                target_keys = tuple(target.key for target in targets)
                if target_keys != announced_targets:
                    if target_keys:
                        names = ", ".join(_target_name(key) for key in target_keys)
                        logger.info(
                            f"Notification delivery ready: {len(target_keys)} "
                            f"target(s) ({names})"
                        )
                    else:
                        logger.info(
                            "Notification delivery disabled: no targets configured"
                        )
                    announced_targets = target_keys
                await self._outbox.initialize_targets(target_keys)

                if await self._deliver_targets(targets):
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

    async def _deliver_targets(self, targets) -> bool:
        if self._sink is None:
            return False
        results = await asyncio.gather(
            *(self._deliver_target(target.key) for target in targets),
            return_exceptions=True,
        )
        delivered = False
        for result in results:
            if isinstance(result, BaseException):
                logger.warning(f"Notification target worker recovered: {result}")
            else:
                delivered = delivered or result
        return delivered

    async def _deliver_target(self, target_key: str) -> bool:
        assert self._sink is not None
        items = await self._outbox.claim_due(target_key, self._batch_interval)
        if not items:
            return False
        target_name = _target_name(target_key)
        item_label = _item_label(items)
        logger.info(
            f"Notification started: {item_label}; target={target_name}; "
            f"releases={len(items)}"
        )
        try:
            batches = self._sink.format_download_batches(target_key, items)
        except Exception as error:
            await self._outbox.delivery_retry(items, str(error))
            logger.warning(
                f"Notification formatting failed: {item_label}; "
                f"target={target_name}; error={error}"
            )
            return False

        included_ids = {item.id for batch in batches for item in batch.items}
        missing = [item for item in items if item.id not in included_ids]
        if missing:
            await self._outbox.delivery_retry(
                missing, "notification formatter omitted claimed items"
            )
            logger.warning(
                f"Notification formatter skipped {len(missing)} release(s); "
                f"target={target_name}; delivery will retry"
            )

        sent_batches = 0
        sent_items = 0
        failed_batches = 0
        for batch in batches:
            batch_items = list(batch.items)
            try:
                success = await self._sink.send_to_target(target_key, batch.message)
            except Exception as error:
                await self._outbox.delivery_retry(batch_items, str(error))
                failed_batches += 1
                logger.warning(
                    f"Notification send failed: {item_label}; "
                    f"target={target_name}; error={error}"
                )
                continue
            if success:
                await self._outbox.delivery_succeeded(batch_items)
                sent_batches += 1
                sent_items += len(batch_items)
            else:
                await self._outbox.delivery_retry(
                    batch_items, "notification target failed after retries"
                )
                failed_batches += 1
        if sent_batches:
            logger.info(
                f"Notification sent: {item_label}; target={target_name}; "
                f"batches={sent_batches}, releases={sent_items}"
            )
        if failed_batches:
            logger.warning(
                f"Notification queued for retry: {item_label}; "
                f"target={target_name}; failed_batches={failed_batches}"
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


def _target_name(target_key: str) -> str:
    return target_key.partition(":")[0] or "unknown"


def _item_label(items) -> str:
    titles = [str(getattr(item, "title", "")).strip() for item in items]
    titles = [title for title in titles if title]
    if not titles:
        return "download batch"
    if len(titles) == 1:
        return titles[0]
    return f"{titles[0]} (+{len(titles) - 1} more)"
