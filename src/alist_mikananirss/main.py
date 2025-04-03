import argparse
import asyncio
import os
import sys

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
from alist_mikananirss.extractor import Extractor, LLMExtractor, create_llm_provider


def init_logging(cfg: AppConfig):
    log_level = cfg.dev.log_level
    logger.remove()

    # 确保日志目录存在
    os.makedirs("log", exist_ok=True)

    # 使用loguru的动态日期格式化功能
    log_filename = "log/alist_mikanrss_{time:YYYY-MM-DD}.log"
    logger.add(
        log_filename, rotation="00:00", retention="7 days", level=log_level, mode="a"
    )
    logger.add(sys.stderr, level=log_level)


def init_proxies(cfg: AppConfig):
    proxies = cfg.common.proxies
    if not proxies:
        return
    if "http" in proxies:
        os.environ["HTTP_PROXY"] = proxies["http"]
    if "https" in proxies:
        os.environ["HTTPS_PROXY"] = proxies["https"]


def init_notification(cfg: AppConfig):
    notification_bots = []
    if not cfg.notification.enable:
        return
    for bot_cfg in cfg.notification.bots:
        if bot_cfg.bot_type == "telegram":
            bot = BotFactory.create_bot(
                BotType.TELEGRAM,
                bot_token=bot_cfg.token,
                user_id=bot_cfg.user_id,
            )
            notification_bots.append(NotificationBot(bot))
        elif bot_cfg.bot_type == "pushplus":
            bot = BotFactory.create_bot(
                BotType.PUSHPLUS,
                user_token=bot_cfg.token,
                channel=bot_cfg.channel,
            )
            notification_bots.append(NotificationBot(bot))
    NotificationSender.initialize(notification_bots, cfg.notification.interval_time)


async def run():
    parser = argparse.ArgumentParser(description="Alist Mikanani RSS")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the configuration file",
    )

    args = parser.parse_args()

    cfg_manager = ConfigManager()
    cfg = cfg_manager.load_config(args.config)
    # logger
    init_logging(cfg)

    logger.info("Loaded config Successfully")
    logger.info(f"Config: \n{cfg}")

    # proxy
    init_proxies(cfg)

    # database
    db = await SubscribeDatabase.create()

    # alist
    alist_client = Alist(cfg.alist.base_url, cfg.alist.token, cfg.alist.downloader)
    alist_ver = await alist_client.get_alist_ver()
    if alist_ver < "3.42.0":
        raise ValueError(f"Unsupported Alist version: {alist_ver}")

    # download manager
    DownloadManager.initialize(
        alist_client=alist_client,
        base_download_path=cfg.alist.download_path,
        use_renamer=cfg.rename.enable,
        need_notification=cfg.notification.enable,
        db=db,
    )

    # extractor
    if cfg.rename.enable:
        extractor_cfg = cfg.rename.extractor
        type_ = extractor_cfg.extractor_type
        extractor = None
        if type_ == "openai":
            llm_provider = create_llm_provider(
                "openai",
                api_key=extractor_cfg.api_key,
                base_url=extractor_cfg.base_url,
                model=extractor_cfg.model,
            )
            extractor = LLMExtractor(llm_provider, extractor_cfg.output_type)
        elif type_ == "deepseek":
            llm_provider = create_llm_provider(
                "deepseek",
                api_key=extractor_cfg.api_key,
                base_url=extractor_cfg.base_url,
            )
            extractor = LLMExtractor(llm_provider, extractor_cfg.output_type)
        else:
            raise ValueError(f"Unsupported extractor type: {type_}")
        Extractor.initialize(extractor)

        AnimeRenamer.initialize(alist_client, cfg.rename.rename_format)

    # remapper
    if cfg.rename.remap.enable:
        cfg_path = cfg.rename.remap.cfg_path
        RemapperManager.load_remappers_from_cfg(cfg_path)

    # rss monitor
    regex_filter = RegexFilter()
    filters_name = cfg.mikan.filters
    regex_pattern = cfg.mikan.regex_pattern
    regex_filter.update_regex(regex_pattern)
    for name in filters_name:
        regex_filter.add_pattern(name)

    subscribe_url = cfg.mikan.subscribe_url
    rss_monitor = RssMonitor(
        subscribe_urls=subscribe_url,
        db=db,
        filter=regex_filter,
        use_extractor=cfg.rename.enable,
    )
    rss_monitor.set_interval_time(cfg.common.interval_time)

    tasks = []
    tasks.append(rss_monitor.run())
    # notification
    if cfg.notification.enable:
        init_notification(cfg)
        tasks.append(NotificationSender.run())

    # Initialize bot assistant
    if cfg.bot_assistant.enable:
        # Only telegram bot is supported now
        if cfg.bot_assistant.bots[0].bot_type == "telegram":
            bot_assistant = BotAssistant(cfg.bot_assistant.bots[0].token, rss_monitor)
            tasks.append(bot_assistant.run())

    try:
        await asyncio.gather(*tasks)
    finally:
        # cleanup after program exit
        await db.close()
        await alist_client.close()
        if cfg.bot_assistant.enable:
            await bot_assistant.stop()


def main():
    asyncio.run(run())
