from typing import Literal

from pydantic import BaseModel, Field


class TelegramBotAssistantConfig(BaseModel):
    bot_type: Literal["telegram"]
    token: str = Field(..., description="The token for the Telegram bot.")
