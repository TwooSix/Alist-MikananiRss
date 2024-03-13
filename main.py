import asyncio
from asyncio import Queue
from enum import Enum

from loguru import logger

from core.alist import Alist
from core.bot import NotificationBot, NotificationMsg
from core.common import initializer
from core.common.config_loader import ConfigLoader
from core.downloader import AlistDownloader
from core.monitor import MikanRSSMonitor

new_res_q = Queue()
downloading_res_q = Queue()
success_res_q = Queue()
config_loader = ConfigLoader("config.yaml")


class RunMode(Enum):
    UpdateMonitor = 0
    DownloadOldAnime = 1


async def send_notification(
    success_res_q: Queue, notification_bots: list[NotificationBot]
):
    while True:
        success_resources = []
        while not success_res_q.empty():
            success_resources.append(await success_res_q.get())
        if success_resources:
            msg = NotificationMsg.from_resources(success_resources)
            results = await asyncio.gather(
                *[bot.send_message(msg) for bot in notification_bots],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.error(result)
        await asyncio.sleep(10)


async def refresh_token(alist_client: Alist, interval_time: int):
    while True:
        try:
            user_name = config_loader.get("alist.user_name")
            password = config_loader.get("alist.password")
            await alist_client.login(user_name, password)
            logger.debug("Refresh token")
            await asyncio.sleep(interval_time)
        except Exception as e:
            logger.error(e)


@logger.catch
async def main():
    # init
    initializer.setup_logger()
    initializer.setup_proxy()
    alist_client = await initializer.init_alist()
    regex_filter = initializer.init_regex_filter()
    notification_bots = initializer.init_notification_bots()
    downloader = AlistDownloader(alist_client)
    download_monitor = initializer.init_download_monitor(alist_client)
    rss_url = config_loader.get("mikan.subscribe_url")
    rss_monitor = MikanRSSMonitor(
        rss_url,
        filter=regex_filter,
    )
    interval_time = config_loader.get("common.interval_time")

    tasks = [
        refresh_token(alist_client, 60 * 60),
        rss_monitor.run(new_res_q, interval_time),
        downloader.run(
            new_res_q, downloading_res_q, config_loader.get("alist.download_path")
        ),
        download_monitor.run(downloading_res_q, success_res_q),
    ]
    tasks.append(send_notification(success_res_q, notification_bots))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
