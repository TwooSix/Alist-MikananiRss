import pytest

from core.bot import NotificationBot, NotificationMsg, TelegramBot
from core.common import config_loader


class TestNotificationMsg:
    @pytest.fixture
    def null_msg(self):
        msg = NotificationMsg()
        return msg

    def test_null_msg(self, null_msg):
        assert not null_msg


class TestNotificationBot:
    @pytest.fixture
    def tele_info(self):
        tele_info = {
            "BotToken": config_loader.get_bot_token(),
            "UserID": config_loader.get_user_id(),
        }
        return tele_info

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

    @pytest.fixture
    def tg_bot_md(self, tele_info):
        handler = TelegramBot(tele_info["BotToken"], tele_info["UserID"])
        bot = NotificationBot(handler)
        return bot

    def test_telegram_notify_md(self, tg_bot_md, msg):
        res = tg_bot_md.send_message(msg)
        assert res
