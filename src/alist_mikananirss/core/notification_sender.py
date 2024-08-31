import asyncio
from typing import List

from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from alist_mikananirss.bot import NotificationBot, NotificationMsg
from alist_mikananirss.websites import ResourceInfo


class NotificationSender:
    _instance = None
    notification_bots: List[NotificationBot] = []
    _queue: asyncio.Queue = None
    _interval: int = 60
    _max_retries = 3

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
    def initialize(cls, notification_bots: List[NotificationBot], interval: int = 60):
        cls._instance = NotificationSender()
        cls._instance.notification_bots = notification_bots
        cls._instance._queue = asyncio.Queue()
        cls._instance._interval = interval
        asyncio.create_task(cls._instance._run())

    @classmethod
    def set_notification_bots(cls, notification_bots: List[NotificationBot]):
        cls._instance.notification_bots = notification_bots

    @classmethod
    async def add_resource(cls, resource: ResourceInfo):
        await cls._instance._queue.put(resource)

    @classmethod
    def set_interval(cls, interval: int):
        cls._instance._interval = interval

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
