from enum import Enum

import aiohttp

from . import BotBase


class PushPlusChannel(Enum):
    WECHAT = "wechat"
    WEBHOOK = "webhook"
    CP = "cp"
    MAIL = "mail"


class PushPlusBot(BotBase):
    def __init__(self, user_token, channel=None) -> None:
        self.user_token = user_token
        if channel:
            try:
                self.channel = PushPlusChannel(channel)
            except ValueError:
                raise ValueError(f"Invalid channel: {channel}")
        else:
            self.channel = PushPlusChannel.WECHAT

    async def send_message(self, message: str) -> bool:
        api_url = f"http://www.pushplus.plus/send/{self.user_token}"
        body = {
            "title": "Alist MikananiRSS更新推送",
            "content": message,
            "channel": self.channel.value,
            "template": "html",
        }
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(api_url, json=body) as response:
                response.raise_for_status()
        return True
