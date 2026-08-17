from __future__ import annotations

from openlist_ani.integrations.messaging.feishu import FeishuMessenger
from openlist_ani.integrations.messaging.state_store import MessagingStateStore

from .base import BotBase


class FeishuBot(BotBase):
    message_limit = 10000

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        receive_id: str | None = None,
        receive_id_type: str | None = None,
        domain: str = "feishu",
        state_dir: str = "data/messaging",
        messenger: FeishuMessenger | None = None,
    ) -> None:
        self.receive_id = receive_id
        self.receive_id_type = receive_id_type
        self.app_id = app_id
        self._messenger = messenger or FeishuMessenger(
            app_id=app_id,
            app_secret=app_secret,
            domain=domain,
            store=MessagingStateStore(state_dir),
        )

    def notification_identity(self) -> str:
        return f"{self.app_id}:{self.receive_id_type}:{self.receive_id}"

    async def send_message(self, message: str) -> bool:
        return await self._messenger.send_text(
            self.receive_id,
            message,
            receive_id_type=self.receive_id_type,
        )
