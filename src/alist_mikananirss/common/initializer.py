import os
import sys

from loguru import logger

from alist_mikananirss.alist import Alist, AlistConfig
from alist_mikananirss.bot import BotFactory, BotType, NotificationBot
from alist_mikananirss.common.config_loader import ConfigLoader
from alist_mikananirss.core import (
    AnimeRenamer,
    DownloadManager,
    NotificationSender,
    RegexFilter,
    RemapperManager,
    RssMonitor,
)
from alist_mikananirss.extractor import ChatGPTExtractor, Extractor

config_loader = None


def read_config(cfg_path: str):
    global config_loader
    config_loader = ConfigLoader(cfg_path)


def setup_logger():
    log_level = config_loader.get("dev.log_level", default="INFO")
    assert log_level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    logger.remove()
    logger.add("log/main_{time}.log", retention="7 days", level=log_level)
    logger.add(sys.stderr, level=log_level)  # 添加新的 handler 且设置等级为 INFO


def setup_proxy():
    proxies = config_loader.get("common.proxies", {})
    if "http" in proxies:
        os.environ["HTTP_PROXY"] = proxies["http"]
    if "https" in proxies:
        os.environ["HTTPS_PROXY"] = proxies["https"]


async def init_alist():
    base_url = config_loader.get("alist.base_url")
    downloader_type = config_loader.get("alist.downloader")
    token = config_loader.get("alist.token")
    acfg = AlistConfig(base_url, token, downloader_type)
    alist_client = Alist(acfg)
    alist_ver = await alist_client.get_alist_ver()
    if alist_ver < "3.29.0":
        raise ValueError(f"Unsupported Alist version: {alist_ver}")
    return alist_client


def init_extrator():
    rename_cfg = config_loader.get("rename", None)
    if rename_cfg is None:
        return None
    elif "chatgpt" in rename_cfg:
        chatgpt_cfg = rename_cfg["chatgpt"]
        chatgpt = ChatGPTExtractor(
            chatgpt_cfg["api_key"],
            chatgpt_cfg.get("base_url"),
            chatgpt_cfg.get("model"),
        )
        Extractor.initialize(chatgpt)
    else:
        raise ValueError("Invalid rename config, extractor is required")


def init_notification_bots() -> list[NotificationBot]:
    notification_bots = []
    tg_config = config_loader.get("notification.telegram", None)
    if tg_config:
        bot_token = config_loader.get("notification.telegram.bot_token")
        user_id = config_loader.get("notification.telegram.user_id")
        bot = BotFactory.create_bot(
            BotType.TELEGRAM, bot_token=bot_token, user_id=user_id
        )
        notification_bots.append(NotificationBot(bot))

    pushplus_config = config_loader.get("notification.pushplus", None)
    if pushplus_config:
        user_token = config_loader.get("notification.pushplus.token")
        channel = config_loader.get("notification.pushplus.channel", None)
        bot = BotFactory.create_bot(
            BotType.PUSHPLUS, user_token=user_token, channel=channel
        )
        notification_bots.append(NotificationBot(bot))
    return notification_bots


def init_notification_sender():
    notification_bots = init_notification_bots()
    interval_time = config_loader.get("common.interval_time", 300)
    interval_time = config_loader.get("notification.interval_time", interval_time)
    NotificationSender.initialize(notification_bots, interval_time)


def init_resource_filter():
    regex_filter = RegexFilter()
    filters_name = config_loader.get("mikan.filters", [])
    regex_pattern = config_loader.get("mikan.regex_pattern", None)
    regex_filter.update_regex(regex_pattern)
    for name in filters_name:
        regex_filter.add_pattern(name)
    return regex_filter


async def init_rss_monitor(regex_filter: RegexFilter):
    subscribe_url = config_loader.get("mikan.subscribe_url")
    use_extractor = False if config_loader.get("rename", None) is None else True
    rss_monitor = RssMonitor(
        subscribe_url,
        filter=regex_filter,
        use_extractor=use_extractor,
    )
    await rss_monitor.initialize()
    interval_time = config_loader.get("common.interval_time", 300)
    if interval_time < 0:
        raise ValueError("Invalid interval time")
    rss_monitor.set_interval_time(interval_time)
    return rss_monitor


async def init_download_manager(alist_client: Alist):
    download_path = config_loader.get("alist.download_path")
    use_renamer = False if config_loader.get("rename", None) is None else True
    need_notification = (
        False if config_loader.get("notification", None) is None else True
    )
    await DownloadManager.initialize(
        alist_client, download_path, use_renamer, need_notification
    )


def init_renamer(alist_client: Alist):
    def check_rename_format(rename_format: str):
        # Check if there are unknown keys in rename format
        from collections import defaultdict

        all_key_test_data = {
            "name": "test",
            "season": 1,
            "episode": 1,
            "fansub": "fansub",
            "quality": "1080p",
            "language": "简体中文",
        }
        # if the key in rename_format is not in all_key_test_data, it will be replaced by "undefined"
        safe_dict = defaultdict(lambda: "undefined", all_key_test_data)
        res = rename_format.format_map(safe_dict)
        if "undefined" in res:
            unknown_keys = [
                key for key, value in safe_dict.items() if value == "undefined"
            ]
            raise KeyError(f"Error keys in rename format: {', '.join(unknown_keys)}")

    rename_cfg = config_loader.get("rename", None)
    if rename_cfg is not None:
        rename_format = config_loader.get("rename.rename_format", None)
        if rename_format:
            check_rename_format(rename_format)
        AnimeRenamer.initialize(alist_client, rename_format)


def init_remappers():
    if config_loader.get("rename.remap.enable", False):
        cfg_path = config_loader.get("rename.remap.cfg_path", "remap.yaml")
        remap_config = ConfigLoader(cfg_path)
        cfgs = remap_config.get("remap")
        for cfg in cfgs:
            from_cfg = cfg["from"]
            to_cfg = cfg["to"]
            RemapperManager.add_remapper(from_cfg, to_cfg)
