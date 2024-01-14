import time
from queue import Queue

from loguru import logger

import functional
from core.alist import Alist
from core.bot import NotificationBot
from core.common import config_loader, initializer
from core.common.globalvar import executor
from core.monitor import AlistDownloadMonitor, MikanRSSMonitor

download_task_queue = Queue()
success_download_queue = Queue()


def check_update(
    alist_client: Alist,
    rss_monitor: MikanRSSMonitor,
    download_monitor_thread: AlistDownloadMonitor,
    notification_bots: list[NotificationBot],
):
    user_name = config_loader.get_user_name()
    password = config_loader.get_password()
    download_path = config_loader.get_download_path()
    status, msg = alist_client.login(user_name, password)
    if not status:
        logger.error(msg)
    else:
        try:
            logger.info("Start update checking")
            # Step 1: Get new resources
            new_resources = rss_monitor.get_new_resource()
            if not new_resources:
                logger.info("No new resources")
                return
            # Step 2: Start to download
            success_resources = functional.download_new_resources(
                alist_client, new_resources, download_path
            )
            # Step 3: Send notification
            functional.send_notification(notification_bots, success_resources)
            # Step 4: wait for download complete
            for resource in success_resources:
                download_task_queue.put(resource)
                # Step 5: insert downloaded resource to database
                rss_monitor.db.insert_from_mikan_resource(resource)
            if not download_monitor_thread.is_running():
                download_monitor_thread.start()
            # Step 6: Rename downloaded resource (in AlistDownloadMonitor thread)
        except Exception as e:
            logger.error(e)


@logger.catch
def main():
    initializer.setup_logger()
    initializer.setup_proxy()
    alist_client = initializer.init_alist()
    notification_bots = initializer.init_notification_bot()
    regex_filter = initializer.init_regex_filter()

    subscribe_url = config_loader.get_subscribe_url()
    rss_monitor = MikanRSSMonitor(
        subscribe_url,
        filter=regex_filter,
    )

    download_monitor_thread = initializer.init_download_monitor(
        alist_client, download_task_queue, success_download_queue
    )

    interval_time = config_loader.get_interval_time()

    # start main loop
    if interval_time < 0:
        interval_time = 0
    execute_once = interval_time == 0

    while interval_time > 0 or execute_once:
        check_update(
            alist_client, rss_monitor, download_monitor_thread, notification_bots
        )
        if execute_once:
            break

        if interval_time > 0:
            time.sleep(interval_time)

    # wait for thread complete
    if download_monitor_thread.is_running():
        download_monitor_thread.wait()


if __name__ == "__main__":
    main()
    executor.shutdown(wait=True)
