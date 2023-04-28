DOMAIN = "www.example.com"

USER_NAME = "username"

PASSWORD = "password"

DOWNLOAD_PATH = "AliYun/Anime"

REGEX_PATTERN = {
    "简体": r"(简体)|(简中)|(简日)|(CHS)",
    "繁体": r"(繁体)|(繁中)|(繁日)|(CHT)",
    "1080": r"(1080[pP])",
    "非合集": r"^((?!合集).)*$",
}

SUBSCRIBE_URL = "https://mikanani.me/RSS/MyBangumi?token=xxx"

FILTERS = ["1080", "非合集"]

INTERVAL_TIME = 0  # 定时执行的间隔时间，单位为秒，0 为只运行一次

# ==================== Telegram Bot ====================
TELEGRAM_NOTIFICATION = False  # 是否开启 Telegram 通知, True 开启, False 关闭
BOT_TOKEN = ""  # 你的 Telegram 用户 ID
USER_ID = ""  # 你的 Telegram Bot Token
