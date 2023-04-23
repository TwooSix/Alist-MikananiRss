DOMAIN = "www.example.com"

USER_NAME = "username"

PASSWORD = "password"

DOWNLOAD_PATH = "AliYun/Anime"

RSS_FILTER = {
    "简体": r"(简体)|(简中)|(简日)|(CHS)",
    "繁体": r"(繁体)|(繁中)|(繁日)|(CHT)",
    "1080": r"(1080[pP])",
    "非合集": r"^((?!合集).)*$",
}

RSS = [
    {
        "url": "https://mikanani.me/RSS/Bangumi?bangumiId=2970&subgroupid=357",
        "filter": ["简体", "1080", "非合集"],
        "subFolder": "地狱乐",  # 下载至 {downloadPath}/地狱乐
    },
    {
        "url": "https://mikanani.me/RSS/Bangumi?bangumiId=2996&subgroupid=382",
        "filter": ["简体", "1080", "非合集"],
        # 不填写，则下载至 {downloadPath}
    },
    {
        "url": "https://mikanani.me/RSS/Bangumi?bangumiId=3005&subgroupid=583",
        "filter": ["繁体", "1080", "非合集"],
        "subFolder": "__AUTO__",  # 程序会自动获取番剧名字，并下载至 {downloadPath}}/{番剧名}
    },
]

# ==================== Telegram Bot ====================
TELEGRAM_NOTIFICATION = False  # 是否开启 Telegram 通知, True 开启, False 关闭
BOT_TOKEN = ""  # 你的 Telegram Bot Token
USER_ID = ""  # 你的 Telegram 用户 ID
