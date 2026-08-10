from __future__ import annotations

from types import SimpleNamespace

import pytest

from openlist_ani.adapters.notifications.bot.base import BotBase
from openlist_ani.adapters.notifications.formatter import NotificationFormatter
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
    manager = NotificationManager([FailingBot()])
    with pytest.raises(RuntimeError, match="startup failed"):
        await manager.start()


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


def test_single_episode_notification_keeps_legacy_format():
    formatter = NotificationFormatter()
    item = SimpleNamespace(
        anime_name="Example",
        title="Example S01E01",
        summary={
            "success_count": 1,
            "skipped_count": 0,
            "failed_count": 0,
            "deleted_count": 0,
            "warning_count": 0,
            "successful_episodes": ["S01E01"],
            "items": [{"state": "completed"}],
        },
    )

    batch = formatter.batch_messages([item], 4096)[0]

    assert batch.message == "你订阅的番剧更新啦：\n\n[Example]:\n  - Example S01E01"


def test_collection_notification_is_one_parent_summary():
    formatter = NotificationFormatter()
    item = SimpleNamespace(
        anime_name="Example",
        title="Example 01-03",
        summary={
            "success_count": 2,
            "skipped_count": 1,
            "failed_count": 1,
            "deleted_count": 3,
            "warning_count": 2,
            "successful_episodes": [
                {"season": 1, "episode": 1},
                {"season": 1, "episode": 2},
            ],
            "items": [
                {"state": "completed"},
                {"state": "completed"},
                {"state": "skipped"},
                {"state": "failed"},
            ],
        },
    )

    batch = formatter.batch_messages([item], 4096)[0]

    assert batch.items == (item,)
    assert "成功 2 集，跳过 1 项，失败 1 项，删除 3 个文件，警告 2 项" in batch.message
    assert "成功集：S01E01、S01E02" in batch.message
