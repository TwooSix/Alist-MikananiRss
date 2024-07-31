import asyncio

from loguru import logger

from alist_mikananirss.bot import NotificationBot, NotificationMsg
from alist_mikananirss.websites import ResourceInfo


class NotificationSender:
    _instance = None
    notification_bots: list[NotificationBot] = []

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            raise RuntimeError("NotificationSender is not initialized")
        return cls._instance

    @classmethod
    def initialize(cls, notification_bots: list[NotificationBot]):
        cls._instance = NotificationSender()
        cls._instance.notification_bots = notification_bots

    @classmethod
    def set_notification_bots(cls, notification_bots: list[NotificationBot]):
        cls._instance.notification_bots = notification_bots

    @classmethod
    async def send(cls, resources: list[ResourceInfo]):
        if not cls._instance.notification_bots:
            return
        if resources:
            msg = NotificationMsg.from_resources(resources)
            logger.debug(f"Send notification\n: {msg}")
            results = await asyncio.gather(
                *[bot.send_message(msg) for bot in cls._instance.notification_bots],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.error(result)
