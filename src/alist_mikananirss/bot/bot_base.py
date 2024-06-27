from abc import ABC, abstractmethod
from enum import Enum


class BotType(Enum):
    TELEGRAM = 0

class BotBase(ABC):
    def __init__(self) -> None:
        super().__init__()

    @abstractmethod
    async def send_message(self, message: str) -> bool:
        raise NotImplementedError
