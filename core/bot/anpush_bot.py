import aiohttp

from . import BotBase, MsgType


class AnpushBot(BotBase):
    def __init__(self, token, channel_id, msg_type=MsgType.NORMAL) -> None:
        self.token = token
        self.channel_id = channel_id
        self.support_markdown = False
        self.message_type = msg_type

    async def send_message(self, message: str) -> bool:
        """Send message via Anpush"""
        api_url = f"https://api.anpush.com/push/{self.token}"
        body = {
            "title": "番剧更新通知",
            "content": message,
            "channel": self.channel_id,
        }
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(api_url, json=body) as response:
                response.raise_for_status()
        return True
