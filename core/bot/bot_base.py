from abc import ABC, abstractmethod
from enum import Enum


class BotType(Enum):
    TELEGRAM = 0


class MsgType(Enum):
    NORMAL = 0
    MARKDOWN = 1
    HTML = 2


class BotBase(ABC):
    def __init__(self) -> None:
        super().__init__()
        self.message_type = MsgType.NORMAL

    @abstractmethod
    def send_message(self, message: str) -> bool:
        raise NotImplementedError
