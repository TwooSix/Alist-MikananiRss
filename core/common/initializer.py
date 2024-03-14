import os
import sys

from loguru import logger

from core.alist import Alist
from core.bot import NotificationBot, TelegramBot
from core.common.config_loader import ConfigLoader
from core.common.extractor import ChatGPT, Regex
from core.common.filters import RegexFilter
from core.downloader import AlistDownloader
from core.monitor import AlistDownloadMonitor, MikanRSSMonitor

config_loader = ConfigLoader("config.yaml")


def setup_logger():
    log_level = config_loader.get("dev.log_level", "INFO")
    assert log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    logger.remove()
    logger.add("log/main_{time}.log", retention="7 days", level=log_level)
    logger.add(sys.stderr, level=log_level)  # 添加新的 handler 且设置等级为 INFO


def setup_proxy():
    # proxy init
    proxies = config_loader.get("common.proxies", {})
    if "http" in proxies:
        os.environ["HTTP_PROXY"] = proxies["http"]
    if "https" in proxies:
        os.environ["HTTPS_PROXY"] = proxies["https"]


async def init_alist():
    # alist init
    base_url = config_loader.get("alist.base_url")
    downloader_type = config_loader.get("alist.downloader")
    token = config_loader.get("alist.token")
    alist_client = Alist(base_url, downloader_type, token)
    alist_ver = await alist_client.get_alist_ver()
    if alist_ver < "3.29.0":
        raise ValueError(f"Unsupported Alist version: {alist_ver}")
    return alist_client


def init_extrator():
    try:
        rename_cfg = config_loader.get("rename")
    except KeyError:
        return None
    if "chatgpt" in rename_cfg:
        chatgpt_cfg = rename_cfg["chatgpt"]
        chatgpt = ChatGPT(
            chatgpt_cfg["api_key"],
            chatgpt_cfg.get("base_url"),
            chatgpt_cfg.get("model"),
        )
        return chatgpt
    elif "regex" in rename_cfg:
        regex_extractor = Regex()
        return regex_extractor
    else:
        raise ValueError("Invalid rename config, extractor is required")


def init_notification_bots():
    # init notification bot
    notification_bots = []
    tg_config = config_loader.get("notification.telegram", False)
    if tg_config:
        bot_token = config_loader.get("notification.telegram.bot_token")
        user_id = config_loader.get("notification.telegram.user_id")
        bot = TelegramBot(bot_token, user_id)
        notification_bots.append(NotificationBot(bot))
    return notification_bots


def init_regex_filter():
    # init resource filters
    regex_filter = RegexFilter()
    filters_name = config_loader.get("mikan.filters", [])
    regex_pattern = config_loader.get("mikan.regex_pattern", {})
    regex_filter.update_regex(regex_pattern)
    for name in filters_name:
        regex_filter.add_pattern(name)
    return regex_filter


def init_mikan_rss_monitor(regex_filter: RegexFilter):
    # init rss manager
    subscribe_url = config_loader.get("mikan.subscribe_url")
    extrator = init_extrator()
    rss_monitor = MikanRSSMonitor(
        subscribe_url,
        filter=regex_filter,
        extractor=extrator,
    )
    return rss_monitor


def init_download_monitor(alist_client: Alist):
    download_path = config_loader.get("alist.download_path")
    try:
        rename_cfg = config_loader.get("rename")
    except KeyError:
        rename_cfg = None
    use_renamer = False
    if rename_cfg is not None:
        use_renamer = True
    download_monitor_thread = AlistDownloadMonitor(
        alist_client,
        download_path,
        use_renamer,
    )
    return download_monitor_thread


def init_alist_downloader(alist_client: Alist):
    try:
        rename_cfg = config_loader.get("rename")
    except KeyError:
        rename_cfg = None
    use_renamer = False
    if rename_cfg is not None:
        use_renamer = True
    downloader = AlistDownloader(alist_client, use_renamer)
    return downloader
