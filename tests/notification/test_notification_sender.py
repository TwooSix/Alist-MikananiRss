import asyncio
from unittest.mock import AsyncMock

import pytest

from alist_mikananirss.bot import NotificationBot
from alist_mikananirss.core import NotificationSender
from alist_mikananirss.websites import ResourceInfo


@pytest.fixture
def reset_notification_sender():
    NotificationSender._instances.pop(NotificationSender, None)
    yield
    NotificationSender._instances.pop(NotificationSender, None)


@pytest.mark.asyncio
async def test_initialization(reset_notification_sender):
    mock_bot = AsyncMock(spec=NotificationBot)
    NotificationSender.initialize([mock_bot], interval=30)
    instance1 = NotificationSender()
    instance2 = NotificationSender()
    assert instance1 == instance2
    assert len(instance1.notification_bots) == 1
    assert instance1._interval == 30
    assert isinstance(instance1._queue, asyncio.Queue)


@pytest.mark.asyncio
async def test_set_notification_bots(reset_notification_sender):
    NotificationSender.initialize([])
    mock_bot1 = AsyncMock(spec=NotificationBot)
    mock_bot2 = AsyncMock(spec=NotificationBot)

    NotificationSender.set_notification_bots([mock_bot1, mock_bot2])

    assert len(NotificationSender().notification_bots) == 2


@pytest.mark.asyncio
async def test_add_resource(reset_notification_sender):
    NotificationSender.initialize([])
    resource = ResourceInfo(
        anime_name="test name",
        resource_title="Test",
        torrent_url="https://test.com",
        published_date="2023-01-01",
    )

    await NotificationSender.add_resource(resource)

    assert NotificationSender()._queue.qsize() == 1


@pytest.mark.asyncio
async def test_set_interval(reset_notification_sender):
    NotificationSender.initialize([], interval=60)

    NotificationSender.set_interval(120)

    assert NotificationSender()._interval == 120


@pytest.mark.asyncio
async def test_run_method(reset_notification_sender):
    mock_bot = AsyncMock(spec=NotificationBot)
    mock_bot.send_message.return_value = asyncio.Future()
    mock_bot.send_message.return_value.set_result(None)

    NotificationSender.initialize([mock_bot], interval=0.1)
    resource = ResourceInfo(
        anime_name="test name",
        resource_title="Test",
        torrent_url="https://test.com",
        published_date="2023-01-01",
    )
    await NotificationSender.add_resource(resource)
    task = asyncio.create_task(NotificationSender.run())
    await asyncio.sleep(0.2)

    mock_bot.send_message.assert_called_once()
    task.cancel()


@pytest.mark.asyncio
async def test_send_method_without_bots(reset_notification_sender):
    NotificationSender.initialize([], interval=0.1)
    resource = ResourceInfo(
        anime_name="test name",
        resource_title="Test",
        torrent_url="https://test.com",
        published_date="2023-01-01",
    )
    await NotificationSender.add_resource(resource)
    task = asyncio.create_task(NotificationSender.run())
    await asyncio.sleep(0.2)
    task.cancel()
