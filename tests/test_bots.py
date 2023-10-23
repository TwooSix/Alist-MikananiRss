import pytest

import config
from core.bot import TelegramBot


class TestTelegramBot:
    @pytest.fixture
    def tele_info(self):
        tele_info = {
            "BotToken": config.BOT_TOKEN,
            "UserID": config.USER_ID,
        }
        return tele_info

    @pytest.fixture
    def msg(self):
        update_info = {
            "name1": ["title1", "title2"],
            "name2": ["title3", "title4"],
        }

        update_anime_list = []
        for name in update_info.keys():
            update_anime_list.append(f"[{name}]")
        anime_name_str = ", ".join(update_anime_list)
        msg = f"你订阅的番剧 {anime_name_str} 更新啦\n"
        for name, titles in update_info.items():
            msg += f"[{name}]:\n"
            msg += "\n".join(titles)
            msg += "\n\n"
        return msg

    @pytest.fixture
    def bot(self, tele_info):
        bot = TelegramBot(tele_info["BotToken"], tele_info["UserID"])
        return bot

    def test_telegram_send_message(self, bot: TelegramBot, msg):
        res = bot.send_message(msg)
        assert res
