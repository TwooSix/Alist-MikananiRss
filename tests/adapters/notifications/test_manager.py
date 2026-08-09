from __future__ import annotations

from types import SimpleNamespace

import pytest

from openlist_ani.adapters.notifications.bot.base import BotBase
from openlist_ani.adapters.notifications.manager import NotificationManager


class FakeBot(BotBase):
    async def start(self) -> None:
        pass

    async def send_message(self, message: str) -> bool:
        return True


class FailingBot(FakeBot):
    async def start(self) -> None:
        raise RuntimeError("startup failed")


@pytest.mark.asyncio
async def test_notification_startup_failure_is_propagated():
    with pytest.raises(RuntimeError, match="startup failed"):
        await NotificationManager([FailingBot()]).start()


def test_oversized_batches_are_split_without_losing_items():
    bot = FakeBot()
    bot.message_limit = 80
    manager = NotificationManager([bot])
    items = [
        SimpleNamespace(id=index, anime_name="Example", title="x" * 35)
        for index in range(3)
    ]

    batches = manager.format_download_batches(manager.targets()[0].key, items)

    assert all(len(batch.message) <= 80 for batch in batches)
    assert [item.id for batch in batches for item in batch.items] == [0, 1, 2]
