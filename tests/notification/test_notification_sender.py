import asyncio
from unittest.mock import Mock

import pytest
from alist_mikananirss.bot import NotificationBot
from alist_mikananirss.core import NotificationSender
from alist_mikananirss.websites import ResourceInfo


@pytest.fixture
def reset_notification_sender():
    NotificationSender._instance = None
    yield
    NotificationSender._instance = None


@pytest.mark.asyncio
async def test_initialization(reset_notification_sender):
    mock_bot = Mock(spec=NotificationBot)
    NotificationSender.initialize([mock_bot], interval=30)

    assert NotificationSender._instance is not None
    assert len(NotificationSender._instance.notification_bots) == 1
    assert NotificationSender._instance._interval == 30
    assert isinstance(NotificationSender._instance._queue, asyncio.Queue)


@pytest.mark.asyncio
async def test_get_instance_without_initialization():
    with pytest.raises(RuntimeError):
        NotificationSender.get_instance()


@pytest.mark.asyncio
async def test_set_notification_bots(reset_notification_sender):
    NotificationSender.initialize([])
    mock_bot1 = Mock(spec=NotificationBot)
    mock_bot2 = Mock(spec=NotificationBot)

    NotificationSender.set_notification_bots([mock_bot1, mock_bot2])

    assert len(NotificationSender._instance.notification_bots) == 2


@pytest.mark.asyncio
async def test_add_resource(reset_notification_sender):
    NotificationSender.initialize([])
    resource = ResourceInfo(
        anime_name="test name",
        resource_title="Test",
        torrent_url="http://test.com",
        published_date="2023-01-01",
    )

    await NotificationSender.add_resource(resource)

    assert NotificationSender._instance._queue.qsize() == 1


@pytest.mark.asyncio
async def test_set_interval(reset_notification_sender):
    NotificationSender.initialize([], interval=60)

    NotificationSender.set_interval(120)

    assert NotificationSender._instance._interval == 120


@pytest.mark.asyncio
async def test_run_method(reset_notification_sender):
    mock_bot = Mock(spec=NotificationBot)
    mock_bot.send_message.return_value = asyncio.Future()
    mock_bot.send_message.return_value.set_result(None)

    NotificationSender.initialize([mock_bot], interval=0.1)
    resource = ResourceInfo(
        anime_name="test name",
        resource_title="Test",
        torrent_url="http://test.com",
        published_date="2023-01-01",
    )
    await NotificationSender.add_resource(resource)

    # Allow some time for the _run method to execute
    await asyncio.sleep(0.2)

    mock_bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_method_with_exception(reset_notification_sender):
    mock_bot1 = Mock(spec=NotificationBot)
    mock_bot1.send_message.return_value = asyncio.Future()
    mock_bot1.send_message.return_value.set_result(None)

    mock_bot2 = Mock(spec=NotificationBot)
    mock_bot2.send_message.side_effect = Exception("Test exception")

    NotificationSender.initialize([mock_bot1, mock_bot2], interval=0.1)
    resource = ResourceInfo(
        anime_name="test name",
        resource_title="Test",
        torrent_url="http://test.com",
        published_date="2023-01-01",
    )
    await NotificationSender.add_resource(resource)

    await asyncio.sleep(0.2)

    mock_bot1.send_message.assert_called_once()
    mock_bot2.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_method_without_bots(reset_notification_sender):
    NotificationSender.initialize([], interval=0.1)
    resource = ResourceInfo(
        anime_name="test name",
        resource_title="Test",
        torrent_url="http://test.com",
        published_date="2023-01-01",
    )
    await NotificationSender.add_resource(resource)

    await asyncio.sleep(0.2)
