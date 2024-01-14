import os
import sys
from queue import Queue

from loguru import logger

from core.alist import Alist
from core.bot import NotificationBot, TelegramBot
from core.common import config_loader
from core.common.filters import RegexFilter
from core.monitor import AlistDownloadMonitor, MikanRSSMonitor


def setup_logger():
    debug_mode = config_loader.get_debug_mode()
    log_level = "DEBUG" if debug_mode else "INFO"
    logger.remove()
    logger.add("log/main_{time}.log", retention="7 days", level=log_level)
    logger.add(sys.stderr, level=log_level)  # 添加新的 handler 且设置等级为 INFO


def setup_proxy():
    # proxy init
    use_proxy = config_loader.get_use_proxy()
    if use_proxy:
        proxies = config_loader.get_proxies()
        if "http" in proxies:
            os.environ["HTTP_PROXY"] = proxies["http"]
        if "https" in proxies:
            os.environ["HTTPS_PROXY"] = proxies["https"]


def init_alist():
    # alist init
    base_url = config_loader.get_base_url()
    downloader_type = config_loader.get_downloader()
    alist_client = Alist(base_url, downloader_type)
    return alist_client


def init_notification_bot():
    # init notification bot
    notification_bots = []
    use_tg_notification = config_loader.get_telegram_notification()
    if use_tg_notification:
        bot_token = config_loader.get_bot_token()
        user_id = config_loader.get_user_id()
        bot = TelegramBot(bot_token, user_id)
        notification_bots.append(NotificationBot(bot))
    return notification_bots


def init_regex_filter():
    # init resource filters
    regex_filter = RegexFilter()
    cfg_filters = config_loader.get_filters()
    regex_pattern = config_loader.get_regex_pattern()
    for filter in cfg_filters:
        regex_filter.add_pattern(regex_pattern[filter])
    return regex_filter


def init_mikan_rss_monitor(regex_filter: RegexFilter):
    # init rss manager
    subscribe_url = config_loader.get_subscribe_url()
    rss_monitor = MikanRSSMonitor(
        subscribe_url,
        filter=regex_filter,
    )
    return rss_monitor


def init_download_monitor(
    alist_client: Alist,
    download_task_queue: Queue,
    success_download_queue: Queue,
):
    download_path = config_loader.get_download_path()
    use_renamer = config_loader.get_use_renamer()
    download_monitor_thread = AlistDownloadMonitor(
        alist_client,
        download_task_queue,
        success_download_queue,
        download_path,
        use_renamer,
    )
    return download_monitor_thread
