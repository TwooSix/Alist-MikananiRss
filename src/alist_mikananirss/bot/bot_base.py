from abc import ABC, abstractmethod
from enum import Enum


class BotType(Enum):
    TELEGRAM = "telegram"
    PUSHPLUS = "pushplus"


class BotBase(ABC):
    def __init__(self) -> None:
        super().__init__()

    @abstractmethod
    async def send_message(self, message: str) -> bool:
        raise NotImplementedError


class BotFactory:
    @staticmethod
    def create_bot(bot_type: str | BotType, **kwargs) -> BotBase:
        if isinstance(bot_type, str):
            try:
                bot_type = BotType(bot_type.lower())
            except ValueError:
                raise ValueError(f"Invalid bot type: {bot_type}")

        if bot_type == BotType.TELEGRAM:
            from .tgbot import TelegramBot

            bot_token = kwargs.get("bot_token")
            user_id = kwargs.get("user_id")
            return TelegramBot(bot_token, user_id)

        elif bot_type == BotType.PUSHPLUS:
            from .pushplus_bot import PushPlusBot

            user_token = kwargs.get("user_token")
            channel = kwargs.get("channel")
            return PushPlusBot(user_token, channel)

        else:
            raise ValueError(f"Unsupported bot type: {bot_type}")
