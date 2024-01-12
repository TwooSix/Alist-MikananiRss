# Alist url
BASE_URL = "http[s]://www.example.com"
# BASE_URL = "http://127.0.0.1:port"

# Alist 用户名和密码
USER_NAME = "username"

PASSWORD = "password"

# 下载路径，相对于 Alist 根目录
DOWNLOAD_PATH = "Onedrive/Anime"

# 正则表达式，用于过滤番剧，不符合表达式的番剧将不会被下载
REGEX_PATTERN = {
    "简体": r"(简体)|(简中)|(简日)|(CHS)",
    "繁体": r"(繁体)|(繁中)|(繁日)|(CHT)",
    "1080": r"(1080[pP])",
    "非合集": r"^(?!.*\d{2}-\d{2}).*",
}

# Mikan 订阅链接
SUBSCRIBE_URL = "https://mikanani.me/RSS/MyBangumi?token=xxx"

# 实际使用的REGEX_PATTERN名字
FILTERS = ["1080", "非合集"]

DOWNLOADER = "aria"  # 下载工具，qbittorent则为"qbit"

INTERVAL_TIME = 0  # 定时执行的间隔时间，单位为秒，0 为只运行一次

# ==================== 代理配置 ====================
USE_PROXY = False  # 是否使用代理
if USE_PROXY:
    PROXIES = {
        "http": "http://127.0.0.1:7890",  # 端口处更改为你的代理端口
        "https": "http://127.0.0.1:7890",
    }
else:
    PROXIES = None

# ==================== Telegram Bot ====================
TELEGRAM_NOTIFICATION = False  # 是否开启 Telegram 通知, True 开启, False 关闭
BOT_TOKEN = ""  # 你的 Telegram 用户 ID
USER_ID = ""  # 你的 Telegram Bot Token

# ==================== ChatGpt ====================
USE_RENAMER = True  # 是否开启重命名, True 开启, False 关闭
CHATGPT_API_KEY = "sk-*"  # 你的 ChatGPT API Key
CHATGPT_BASE_URL = None
# CHATGPT_BASE_URL = "https://www.example.com/v1" # 更改base url为第三方url（不更改填写None）
CHATGPT_MODEL = "gpt-3.5-turbo"

# ==================== For Development ====================
DEBUG_MODE = False  # 开启后输出详细日志
