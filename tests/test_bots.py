import pytest

import config
from core.bot import TelegramBot


class TestTelegramApi:
    @pytest.fixture
    def tele_info(self):
        tele_info = {
            "BotToken": config.BOT_TOKEN,
            "UserID": config.USER_ID,
        }
        return tele_info

    def test_telegram_send_message(self, tele_info):
        telegram = TelegramBot(tele_info["BotToken"], tele_info["UserID"])
        res = telegram.send_message("test")
        assert res
