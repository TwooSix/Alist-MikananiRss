import time

import config
from core import api
from core.bot import TelegramBot
from core.common.logger import Log
from core.rssmanager import RssManager

if __name__ == "__main__":
    Log.init()
    Log.update_level("INFO")

    alist = api.Alist(config.BASE_URL)

    # init notification bot
    notification_bots = []
    if config.TELEGRAM_NOTIFICATION:
        notification_bots.append(TelegramBot(config.BOT_TOKEN, config.USER_ID))

    # init resource filters
    filters = []
    for filter in config.FILTERS:
        filters.append(config.REGEX_PATTERN[filter])

    # init rss manager
    manager = RssManager(
        config.SUBSCRIBE_URL,
        download_path=config.DOWNLOAD_PATH,
        filter=filters,
        alist=alist,
        notification_bots=notification_bots,
    )

    # start main loop
    while config.INTERVAL_TIME > 0:
        try:
            resp = alist.login(config.USER_NAME, config.PASSWORD)
            manager.check_update()
        except Exception as e:
            Log.error(e)
        time.sleep(config.INTERVAL_TIME)

    if config.INTERVAL_TIME == 0:
        try:
            resp = alist.login(config.USER_NAME, config.PASSWORD)
            manager.check_update()
        except Exception as e:
            Log.error(e)
