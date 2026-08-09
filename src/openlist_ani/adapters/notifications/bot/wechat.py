from __future__ import annotations

from openlist_ani.integrations.messaging.wechat_ilink import WechatIlinkMessenger
from .base import BotBase


class WechatBot(BotBase):
    message_limit = 2000

    def __init__(
        self,
        *,
        chat_id: str | None = None,
        account_id: str = "",
        token: str = "",
        base_url: str = "https://ilinkai.weixin.qq.com",
        messenger: WechatIlinkMessenger | None = None,
    ) -> None:
        self.chat_id = chat_id
        self.account_id = account_id
        self._messenger = messenger or WechatIlinkMessenger(
            account_id=account_id,
            token=token,
            base_url=base_url,
            interactive_login=False,
        )

    def notification_identity(self) -> str:
        return f"{self.account_id}:{self.chat_id}"

    async def start(self) -> None:
        await self._messenger.ensure_auth()

    async def send_message(self, message: str) -> bool:
        return await self._messenger.send_text(self.chat_id, message)
