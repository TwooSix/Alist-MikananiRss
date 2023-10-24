import pytest

import config
from core.bot import NotificationBot, NotificationMsg, TelegramBot


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
            "BotToken": config.BOT_TOKEN,
            "UserID": config.USER_ID,
        }
        return tele_info

    @pytest.fixture
    def msg(self):
        msg = NotificationMsg()
        msg.update("name1", ["title1", "title2"])
        msg.update("name2", ["title3", "title4"])
        return msg

    @pytest.fixture
    def tg_bot_md(self, tele_info):
        handler = TelegramBot(tele_info["BotToken"], tele_info["UserID"])
        bot = NotificationBot(handler)
        return bot

    def test_telegram_notify_md(self, tg_bot_md, msg):
        res = tg_bot_md.send_message(msg)
        assert res
