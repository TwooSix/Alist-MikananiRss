import config
import core
import logging
import time

from core import api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    encoding="utf-8",
    handlers=[
        logging.FileHandler("log.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


alist = api.Alist(config.DOMAIN)

notification_bot = None
if config.TELEGRAM_NOTIFICATION:
    notification_bot = api.TelegramBot(config.BOT_TOKEN, config.USER_ID)

filters = []
for filter in config.FILTERS:
    filters.append(config.REGEX_PATTERN[filter])

manager = core.Manager(
    config.SUBSCRIBE_URL,
    download_path=config.DOWNLOAD_PATH,
    filter=filters,
    alist=alist,
    notification_bot=notification_bot,
)

while config.INTERVAL_TIME:
    try:
        resp = alist.login(config.USER_NAME, config.PASSWORD)
        manager.check_update()
    except Exception as e:
        logging.error(e)
    time.sleep(config.INTERVAL_TIME)
