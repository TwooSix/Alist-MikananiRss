from abc import ABC, abstractmethod

class BotBase(ABC):
    def __init__(self) -> None:
        super().__init__()

    @abstractmethod
    async def send_message(self, message: str) -> bool:
        raise NotImplementedError
