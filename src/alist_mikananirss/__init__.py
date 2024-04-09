import asyncio

from loguru import logger

from alist_mikananirss.bot import NotificationBot, NotificationMsg
from alist_mikananirss.common import initializer
from alist_mikananirss.common.globalvar import config_loader, success_res_q


async def send_notification(
    notification_bots: list[NotificationBot], interval_time: int = 10
):
    while True:
        success_resources = []
        while not success_res_q.empty():
            success_resources.append(await success_res_q.get())
        if success_resources:
            msg = NotificationMsg.from_resources(success_resources)
            logger.debug(f"Send notification\n: {msg}")
            results = await asyncio.gather(
                *[bot.send_message(msg) for bot in notification_bots],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.error(result)
        await asyncio.sleep(interval_time)


@logger.catch
async def run():
    # init
    initializer.setup_logger()
    initializer.setup_proxy()
    alist_client = await initializer.init_alist()
    regex_filter = initializer.init_regex_filter()
    notification_bots = initializer.init_notification_bots()
    downloader = initializer.init_alist_downloader(alist_client)
    download_monitor = initializer.init_download_monitor(alist_client)
    rss_monitor = initializer.init_mikan_rss_monitor(regex_filter)
    interval_time = config_loader.get("common.interval_time")
    if interval_time <= 0:
        raise ValueError("Interval time should be greater than 0")

    tasks = [
        rss_monitor.run(interval_time),
        downloader.run(config_loader.get("alist.download_path")),
        download_monitor.run(),
        send_notification(notification_bots, interval_time),
    ]
    await asyncio.gather(*tasks)


def main():
    asyncio.run(run())
