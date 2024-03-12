import argparse
import asyncio
import sys
from enum import Enum
from queue import Queue

from loguru import logger

from core.alist import Alist
from core.bot import NotificationBot, NotificationMsg
from core.common import initializer
from core.common.config_loader import ConfigLoader
from core.downloader import AlistDownloader
from core.monitor import MikanRSSMonitor

download_task_queue = Queue()
success_download_queue = Queue()
config_loader = ConfigLoader("config.yaml")


class RunMode(Enum):
    UpdateMonitor = 0
    DownloadOldAnime = 1


async def check_update(
    alist_client: Alist,
    rss_monitor: MikanRSSMonitor,
    notification_bots: list[NotificationBot],
    mode: RunMode,
):
    download_path = config_loader.get("alist.download_path")
    interval_time = config_loader.get("common.interval_time", 0)
    downloader = AlistDownloader(alist_client)
    keep_run = True

    while keep_run:
        try:
            await alist_client.wait_for_login(timeout=30)
        except asyncio.TimeoutError:
            logger.error("Alist is not login, recheck after 60s.")
            asyncio.sleep(60)

        keep_run = mode == RunMode.UpdateMonitor
        try:
            logger.info("Start update checking")
            # Step 1: Get new resources
            new_resources = await rss_monitor.get_new_resource()
            if not new_resources:
                logger.info("No new resources")
                await asyncio.sleep(interval_time)
                continue
            # Step 2: Start to download
            downloading_resources = await downloader.download(
                download_path, new_resources
            )
            # Step 3: Wait for download complete
            # Step 4: Rename downloaded resource (in download_monitor)
            download_monitor = initializer.init_download_monitor(alist_client)
            success_resources = await download_monitor.wait_succeed(
                downloading_resources
            )
            if mode == RunMode.DownloadOldAnime:
                # DownloadOld mode don't need to modified database and send notification
                return
            if not success_resources:
                continue
            # Step 5: Insert success resources to db
            rss_monitor.mark_downloaded(success_resources)
            # Step 6: Send notification
            msg = NotificationMsg.from_resources(success_resources)
            results = await asyncio.gather(
                *[bot.send_message(msg) for bot in notification_bots],
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, Exception):
                    logger.error(result)
        except Exception as e:
            logger.error(e)
        await asyncio.sleep(interval_time)

async def refresh_token(alist_client: Alist, interval_time: int):
    while True:
        try:
            user_name = config_loader.get("alist.user_name")
            password = config_loader.get("alist.password")
            await alist_client.login(user_name, password)
            await asyncio.sleep(interval_time)
        except Exception as e:
            logger.error(e)



@logger.catch
async def main():
    # read args
    parser = argparse.ArgumentParser(description="Process command line arguments.")
    parser.add_argument(
        "--mode",
        "-m",
        type=int,
        choices=[0, 1],
        default=0,
        help=(
            f"Runmode, {RunMode.UpdateMonitor.value}: UpdateMonitor,"
            f" {RunMode.DownloadOldAnime.value}: DownloadOldAnime"
        ),
    )
    parser.add_argument(
        "--url", "-u", type=str, required=False, help="Rss url of old anime."
    )
    args = parser.parse_args()
    try:
        mode = RunMode(args.mode)
    except ValueError:
        logger.error("Invalid mode")
        sys.exit(1)

    rss_url = args.url
    if mode == RunMode.DownloadOldAnime and rss_url is None:
        logger.error("--mode 1 requires --url to be set.")
        sys.exit(1)

    initializer.setup_logger()
    initializer.setup_proxy()
    alist_client = await initializer.init_alist()
    regex_filter = initializer.init_regex_filter()
    notification_bots = initializer.init_notification_bots()
    if mode == RunMode.UpdateMonitor:
        rss_url = config_loader.get("mikan.subscribe_url")
    rss_monitor = MikanRSSMonitor(
        rss_url,
        filter=regex_filter,
    )
    tasks = [
        check_update(alist_client, rss_monitor, notification_bots, mode),
        refresh_token(alist_client, 60 * 60),
    ]
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
