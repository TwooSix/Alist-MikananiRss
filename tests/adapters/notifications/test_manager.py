from __future__ import annotations

import pytest

from openlist_ani.adapters.notifications.bot.base import BotBase
from openlist_ani.adapters.notifications.manager import NotificationManager
from types import SimpleNamespace


class StartTrackingBot(BotBase):
    def __init__(self) -> None:
        self.started = 0

    async def start(self) -> None:
        self.started += 1

    async def send_message(self, message: str) -> bool:
        return True


class FailingStartBot(BotBase):
    async def start(self) -> None:
        raise RuntimeError("startup failed")

    async def send_message(self, message: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_manager_start_invokes_bot_start_even_without_batching():
    bot = StartTrackingBot()
    manager = NotificationManager([bot])

    await manager.start()

    assert bot.started == 1
    await manager.stop()


@pytest.mark.asyncio
async def test_manager_start_propagates_bot_start_failure():
    manager = NotificationManager([FailingStartBot()])

    with pytest.raises(RuntimeError, match="startup failed"):
        await manager.start()


def test_manager_splits_oversized_batches_without_losing_items():
    bot = StartTrackingBot()
    bot.message_limit = 80
    manager = NotificationManager([bot])
    target = manager.targets()[0]
    items = [
        SimpleNamespace(id=index, anime_name="Example", title="x" * 35)
        for index in range(3)
    ]

    batches = manager.format_download_batches(target.key, items)

    assert len(batches) == 3
    assert all(len(batch.message) <= 80 for batch in batches)
    assert [item.id for batch in batches for item in batch.items] == [0, 1, 2]


def test_manager_truncates_one_item_that_exceeds_channel_limit():
    bot = StartTrackingBot()
    bot.message_limit = 64
    manager = NotificationManager([bot])
    target = manager.targets()[0]
    item = SimpleNamespace(id=1, anime_name="Example", title="x" * 200)

    batch = manager.format_download_batches(target.key, [item])[0]

    assert len(batch.message) == 64
    assert batch.message.endswith("…")
    assert batch.items == (item,)
