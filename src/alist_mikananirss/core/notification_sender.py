import asyncio
from typing import List

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from alist_mikananirss.bot import NotificationBot, NotificationMsg
from alist_mikananirss.websites import ResourceInfo

from ..utils import Singleton


class NotificationSender(metaclass=Singleton):

    def __init__(self, notification_bots: list[NotificationBot], interval: int = 60):
        self.notification_bots = notification_bots
        self._interval = interval
        self._queue = asyncio.Queue()
        self._max_retries = 3

    @classmethod
    def initialize(cls, notification_bots: List[NotificationBot], interval: int = 60):
        cls(notification_bots, interval)

    @classmethod
    def set_notification_bots(cls, notification_bots: List[NotificationBot]):
        instance = cls()
        instance.notification_bots = notification_bots

    @classmethod
    async def add_resource(cls, resource: ResourceInfo):
        instance = cls()
        await instance._queue.put(resource)

    @classmethod
    def set_interval(cls, interval: int):
        instance = cls()
        instance._interval = interval

    async def _run(self):
        while True:
            await asyncio.sleep(self._interval)
            resources = []
            while not self._queue.empty():
                try:
                    resource = self._queue.get_nowait()
                    resources.append(resource)
                except asyncio.QueueEmpty:
                    break
            if resources:
                await self._send(resources)

    @classmethod
    async def run(cls):
        instance = cls()
        await instance._run()

    @classmethod
    def destroy_instance(cls):
        instance = cls()
        if instance._task and not instance._task.done():
            instance._task.cancel()
        NotificationSender._instances.pop(cls)

    async def _send(self, resources: List[ResourceInfo]):
        if not self.notification_bots:
            return
        msg = NotificationMsg.from_resources(resources)
        logger.debug(f"Send notification\n: {msg}")

        tasks = [self._send_with_retry(bot, msg) for bot in self.notification_bots]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Failed to send notification after all retries: {result}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=3, min=5, max=30),
        reraise=True,
    )
    async def _send_with_retry(self, bot: NotificationBot, msg: NotificationMsg):
        try:
            await bot.send_message(msg)
        except Exception as e:
            logger.warning(f"Attempt failed for {type(bot.bot)}: {e}")
            raise
