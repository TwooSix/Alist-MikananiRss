import pytest

from core.bot import NotificationMsg
from core.common import initializer

initializer.setup_proxy()


class TestNotificationMsg:
    @pytest.fixture
    def null_msg(self):
        msg = NotificationMsg()
        return msg

    def test_null_msg(self, null_msg):
        assert not null_msg


class TestNotificationBot:
    @pytest.fixture
    def bots(self):
        _bots = initializer.init_notification_bots()
        return _bots

    @pytest.fixture
    def msg(self):
        msg = NotificationMsg()
        msg.update(
            "name1", ["[fansub1][title1][1][1080p]", "[fansub2][title2][2][1080p]"]
        )
        msg.update(
            "name2", ["[fansub1][title3] 1 [1080p]", "[fansub2] [title4] 2 [1080p]"]
        )
        return msg

    @pytest.mark.asyncio
    async def test_telegram_notify_md(self, bots, msg):
        for bot in bots:
            res = await bot.send_message(msg)
            assert res
