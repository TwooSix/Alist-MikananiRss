import os
import sys
from queue import Queue

from loguru import logger

from core import api
from core.bot import NotificationBot, TelegramBot
from core.common import config_loader
from core.common.filters import RegexFilter
from core.mikan import MikanAnimeResource
from core.monitor import AlistDonwloadMonitor, MikanRSSMonitor

download_task_queue = Queue()
success_download_queue = Queue()


def download_new_resources(
    alist: api.Alist, resources: list[MikanAnimeResource], root_path: str
):
    # group new resource by anime name and season
    resource_group: dict[str, dict[str, list[MikanAnimeResource]]] = {}
    for resource in resources:
        if resource.anime_name not in resource_group:
            resource_group[resource.anime_name] = {}
        if resource.season not in resource_group[resource.anime_name]:
            resource_group[resource.anime_name][resource.season] = []

        resource_group[resource.anime_name][resource.season].append(resource)

    # download new resources by group
    success_resource = []  # the resource that has been started to download successfully
    for name, season_group in resource_group.items():
        for season, resources in season_group.items():
            urls = [resource.torrent_url for resource in resources]
            titles = [resource.resource_title for resource in resources]
            subfolder = os.path.join(name, f"Season {season}")
            download_path = os.path.join(root_path, subfolder)
            # download
            status, msg = alist.add_aria2(download_path, urls)
            if not status:
                logger.error(f"Error when downloading {name}:\n {msg}")
                continue
            titles_str = "\n".join(titles)
            logger.info(f"Start to download {name}:\n {titles_str}")
            success_resource += resources
    return success_resource


if __name__ == "__main__":
    # logger init
    log_level = "DEBUG"
    logger.remove()
    logger.add(sys.stderr, level=log_level)  # 添加新的 handler 且设置等级为 INFO

    # read args
    if len(sys.argv) != 2:
        logger.error("Usage: python main.py <rss_url>")
        exit(1)
    rss_url = sys.argv[1]

    # proxy init
    use_proxy = config_loader.get_use_proxy()
    if use_proxy:
        proxies = config_loader.get_proxies()
        if "http" in proxies:
            os.environ["HTTP_PROXY"] = proxies["http"]
        if "https" in proxies:
            os.environ["HTTPS_PROXY"] = proxies["https"]

    # alist init
    base_url = config_loader.get_base_url()
    alist = api.Alist(base_url)

    # init notification bot
    notification_bots = []
    use_tg_notification = config_loader.get_telegram_notification()
    if use_tg_notification:
        bot_token = config_loader.get_bot_token()
        user_id = config_loader.get_user_id()
        bot = TelegramBot(bot_token, user_id)
        notification_bots.append(NotificationBot(bot))

    # init resource filters
    regex_filter = RegexFilter()
    cfg_filters = config_loader.get_filters()
    regex_pattern = config_loader.get_regex_pattern()
    for filter in cfg_filters:
        regex_filter.add_pattern(regex_pattern[filter])

    # init rss manager
    subscribe_url = config_loader.get_subscribe_url()
    download_path = config_loader.get_download_path()
    rss_monitor = MikanRSSMonitor(
        rss_url,
        filter=regex_filter,
    )

    # start main loop and thread
    user_name = config_loader.get_user_name()
    password = config_loader.get_password()
    interval_time = config_loader.get_interval_time()
    use_renamer = config_loader.get_use_renamer()
    download_monitor_thread = AlistDonwloadMonitor(
        alist, download_task_queue, download_path, use_renamer
    )
    db = rss_monitor.db

    status, msg = alist.login(user_name, password)
    if not status:
        logger.error(msg)
    else:
        try:
            logger.info("Start update checking")
            # Step 1: Get new resources
            new_resources = rss_monitor.get_new_resource()
            if not new_resources:
                logger.info("No new resources")
            else:
                # Step 2: Start to download
                success_resources = download_new_resources(
                    alist, new_resources, download_path
                )
                # Step 3: wait for download complete
                for resource in success_resources:
                    download_task_queue.put(resource)
                if not download_monitor_thread.is_alive():
                    download_monitor_thread = AlistDonwloadMonitor(
                        alist,
                        download_task_queue,
                        success_download_queue,
                        download_path,
                        use_renamer,
                    )
                    download_monitor_thread.start()
                # Step 4: Rename downloaded resource (in AlistDownloadMonitor thread)
        except Exception as e:
            logger.error(e)

    # wait for thread complete
    if download_monitor_thread.is_alive():
        download_monitor_thread.join()
