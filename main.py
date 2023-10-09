import time

import config
from core import api
from core.common.logger import Log
from core.rssmanager import RssManager

Log.init()
Log.update_level("INFO")

alist = api.Alist(config.BASE_URL)

notification_bot = None
if config.TELEGRAM_NOTIFICATION:
    notification_bot = api.TelegramBot(config.BOT_TOKEN, config.USER_ID)

filters = []
for filter in config.FILTERS:
    filters.append(config.REGEX_PATTERN[filter])

manager = RssManager(
    config.SUBSCRIBE_URL,
    download_path=config.DOWNLOAD_PATH,
    filter=filters,
    alist=alist,
    notification_bot=notification_bot,
)

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
