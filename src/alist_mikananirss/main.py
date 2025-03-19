import argparse
import asyncio
import os
import sys
from datetime import datetime

from loguru import logger

from alist_mikananirss import (
    AnimeRenamer,
    AppConfig,
    BotAssistant,
    ConfigManager,
    DownloadManager,
    NotificationSender,
    RegexFilter,
    RemapperManager,
    RssMonitor,
    SubscribeDatabase,
)
from alist_mikananirss.alist import Alist
from alist_mikananirss.bot import BotFactory, BotType, NotificationBot
from alist_mikananirss.extractor import ChatGPTExtractor, Extractor

def init_logging(cfg: AppConfig):
    log_level = cfg.dev_log_level
    logger.remove()
    
    # 确保日志目录存在
    os.makedirs("log", exist_ok=True)
    
    # 使用loguru的动态日期格式化功能
    log_filename = "log/alist_mikanrss_{time:YYYY-MM-DD}.log"
    logger.add(
        log_filename, 
        rotation="00:00", 
        retention="7 days", 
        level=log_level, 
        mode="a"
    )
    logger.add(sys.stderr, level=log_level)


def init_proxies(cfg: AppConfig):
    proxies = cfg.common_proxies
    if not proxies:
        return
    if "http" in proxies:
        os.environ["HTTP_PROXY"] = proxies["http"]
    if "https" in proxies:
        os.environ["HTTPS_PROXY"] = proxies["https"]


def init_notification(cfg: AppConfig):
    notification_bots = []
    if cfg.notification_telegram_enable:
        bot = BotFactory.create_bot(
            BotType.TELEGRAM,
            bot_token=cfg.notification_telegram_bot_token,
            user_id=cfg.notification_telegram_user_id,
        )
        notification_bots.append(NotificationBot(bot))

    if cfg.notification_pushplus_enable:
        bot = BotFactory.create_bot(
            BotType.PUSHPLUS,
            user_token=cfg.notification_pushplus_token,
            channel=cfg.notification_pushplus_channel,
        )
        notification_bots.append(NotificationBot(bot))
    NotificationSender.initialize(notification_bots, cfg.notification_interval_time)


async def run():
    parser = argparse.ArgumentParser(description="Alist Mikanani RSS")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the configuration file",
    )

    args = parser.parse_args()

    cfg_manager = ConfigManager(args.config)
    cfg = cfg_manager.get_config()
    # logger
    init_logging(cfg)

    logger.info("Loaded config Successfully")
    logger.info(f"Config: \n{cfg.format_output_yaml()}")

    # proxy
    init_proxies(cfg)

    # database
    db = await SubscribeDatabase.create()

    # alist
    alist_client = Alist(cfg.alist_base_url, cfg.alist_token, cfg.alist_downloader)
    alist_ver = await alist_client.get_alist_ver()
    if alist_ver < "3.42.0":
        raise ValueError(f"Unsupported Alist version: {alist_ver}")

    # download manager
    DownloadManager.initialize(
        alist_client=alist_client,
        base_download_path=cfg.alist_download_path,
        use_renamer=cfg.rename_enable,
        need_notification=cfg.notification_enable,
        db=db,
    )

    # extractor
    if cfg.rename_enable:
        chatgpt = ChatGPTExtractor(
            api_key=cfg.rename_chatgpt_api_key,
            base_url=cfg.rename_chatgpt_base_url,
            model=cfg.rename_chatgpt_model,
        )
        Extractor.initialize(chatgpt)

    # renamer
    if cfg.rename_enable:
        rename_format = cfg.rename_format
        AnimeRenamer.initialize(alist_client, rename_format)

    # remapper
    if cfg.rename_remap_enable:
        cfg_path = cfg.rename_remap_cfg_path
        RemapperManager.load_remappers_from_cfg(cfg_path)

    # rss monitor
    regex_filter = RegexFilter()
    filters_name = cfg.mikan_filters
    regex_pattern = cfg.mikan_regex_pattern
    regex_filter.update_regex(regex_pattern)
    for name in filters_name:
        regex_filter.add_pattern(name)

    subscribe_url = cfg.mikan_subscribe_url
    rss_monitor = RssMonitor(
        subscribe_urls=subscribe_url,
        db=db,
        filter=regex_filter,
        use_extractor=cfg.rename_enable,
    )
    rss_monitor.set_interval_time(cfg.common_interval_time)

    tasks = []
    # notification
    if cfg.notification_enable:
        init_notification(cfg)
        tasks.append(NotificationSender.run())

    # Initialize bot assistant
    if cfg.bot_assistant_enable:
        bot_assistant = BotAssistant(cfg.bot_assistant_telegram_bot_token, rss_monitor)
        tasks.append(bot_assistant.run())

    tasks.append(rss_monitor.run())

    try:
        await asyncio.gather(*tasks)
    finally:
        # cleanup after program exit
        await db.close()
        if cfg.bot_assistant_enable:
            await bot_assistant.stop()


def main():
    asyncio.run(run())
