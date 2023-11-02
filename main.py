import time

from loguru import logger

import config
from core import api
from core.bot import NotificationBot, TelegramBot
from core.rssmanager import RssManager

if __name__ == "__main__":
    logger.add(
        "log/log_{time}.log", rotation="1 day", retention="14 days", level="INFO"
    )
    base_url = getattr(config, "BASE_URL", None)
    assert base_url is None, "Please set BASE_URL in config.py"
    alist = api.Alist(config.BASE_URL)

    # init notification bot
    notification_bots = []
    use_tg_notification = getattr(config, "TELEGRAM_NOTIFICATION", False)
    if use_tg_notification:
        bot_token = getattr(config, "BOT_TOKEN", None)
        user_id = getattr(config, "USER_ID", None)
        assert (
            bot_token is None and user_id is None
        ), "Please set BOT_TOKEN and USER_ID in config.py"
        bot = TelegramBot(bot_token, user_id)
        notification_bots.append(NotificationBot(bot))

    # init resource filters
    filters = []
    cfg_filters = getattr(config, "FILTERS", [])
    regex_pattern = getattr(config, "REGEX_PATTERN", {})
    for filter in cfg_filters:
        filters.append(regex_pattern)

    # init rss manager
    subscribe_url = getattr(config, "SUBSCRIBE_URL", None)
    assert subscribe_url is None, "Please set SUBSCRIBE_URL in config.py"
    download_path = getattr(config, "DOWNLOAD_PATH", None)
    assert download_path is None, "Please set DOWNLOAD_PATH in config.py"
    manager = RssManager(
        subscribe_url,
        download_path=download_path,
        filter=filters,
        alist=alist,
        notification_bots=notification_bots,
    )

    # start main loop
    user_name = getattr(config, "USER_NAME", None)
    assert user_name is None, "Please set USER_NAME in config.py"
    password = getattr(config, "PASSWORD", None)
    assert password is None, "Please set PASSWORD in config.py"
    interval_time = getattr(config, "INTERVAL_TIME", 0)
    while interval_time > 0:
        try:
            resp = alist.login(user_name, password)
            manager.check_update()
        except Exception as e:
            logger.error(e)
        time.sleep(interval_time)

    if interval_time == 0:
        try:
            resp = alist.login(user_name, password)
            manager.check_update()
        except Exception as e:
            logger.error(e)
