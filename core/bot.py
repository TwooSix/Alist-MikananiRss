from abc import ABC, abstractmethod
from enum import Enum

import requests


class BotType(Enum):
    TELEGRAM = 0


class Bot(ABC):
    @abstractmethod
    def send_message(self, message: str) -> bool:
        raise NotImplementedError


class TelegramBot(Bot):
    def __init__(self, bot_token, user_id) -> None:
        self.bot_token = bot_token
        self.user_id = user_id

    def send_message(self, message: str) -> bool:
        """Send message via Telegram"""
        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        body = {
            "chat_id": self.user_id,
            "text": message,
            "parse_mode": "Markdown",
        }
        response = requests.request("POST", api_url, json=body)
        response.raise_for_status()
        return response.json()
