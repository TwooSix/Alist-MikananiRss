from typing import Literal

from pydantic import BaseModel, Field

from alist_mikananirss.bot import PushPlusChannel


class TelegramConfig(BaseModel):
    bot_type: Literal["telegram"]
    token: str = Field(..., description="Telegram Bot Token")
    user_id: str | int = Field(..., description="Telegram User ID")


class PushPlusConfig(BaseModel):
    bot_type: Literal["pushplus"]
    token: str = Field(..., description="PushPlus Token")
    channel: PushPlusChannel = Field(
        PushPlusChannel.WECHAT, description="PushPlus Channel"
    )
