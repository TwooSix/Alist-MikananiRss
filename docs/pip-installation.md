# PIP 安装指南

通过 PIP 安装是最简单的方式，适合大多数用户。

## 环境要求

- **Python** ≥ 3.11
- **pip**（Python 包管理器）

确认 Python 版本：

```bash
python3 --version
```

## 第一步：安装 Openlist-Ani

```bash
pip install openlist-ani
```

安装完成后会自动注册以下命令：

| 命令 | 用途 |
|------|------|
| `openlist-ani` | 主程序（RSS 监控 + 自动下载 + 重命名） |
| `openlist-ani-assistant` | AI 智能助理（Telegram Bot 或本地 CLI） |

默认 Pi Assistant 不需要额外安装 Node.js/npm。第一次启动时，程序会下载
官方锁定版本的独立包，使用官方 `SHA256SUMS` 校验后原子安装到配置文件旁的
`data/assistant/runtime/pi/`。后续启动直接复用；显式 `executable` 或 PATH 中
已有的 Pi 优先。Windows 缺少 Bash 时还会自动准备官方 PortableGit 到
`data/assistant/runtime/git-bash/`，不修改系统安装或全局 PATH。两种下载都校验
固定 SHA-256；下载或写入失败时不会留下半安装状态，并提示手工安装方式。

## 第二步：创建配置文件

在你想要运行的目录下新建 `config.toml` 文件。以下是**完整配置模板**，请根据需要修改：

```toml
# ============================================================
# Openlist-Ani 完整配置文件
# ============================================================
config_version = 2

# ---------- 后端 API ----------
[backend]
host = "127.0.0.1"   # 绑定地址，127.0.0.1 表示仅本机访问
port = 26666          # 监听端口

# ---------- RSS 订阅 ----------
[rss]
urls = [
    # 在此添加你的 RSS 链接，支持多个
    # "https://mikanani.me/RSS/MyBangumi?token=xxx"
]
interval_time = 300   # 抓取间隔，单位秒（默认 5 分钟）

# ---------- 下载优先级（可选） ----------
# 同一番剧同集存在多个资源时，按优先级自动过滤
# [rss.priority]
# field_order = ["fansub", "quality", "languages"]  # 比较顺序
# fansub = []                # 字幕组优先级（靠前优先）
# quality = ["2160p", "1080p", "720p", "480p", "360p"]  # 清晰度优先级
# languages = []             # 语言优先级，可选: "简", "繁", "日", "英"

# ---------- 代理（可选） ----------
[proxy]
http = ""     # HTTP 代理，如 "http://127.0.0.1:7890"
https = ""    # HTTPS 代理

# ---------- 下载与 OpenList ----------
[downloader]
download_path = "/PikPak/Anime"
rename_format = "{anime_name} S{season:02d}E{episode:02d} {fansub} {quality} {languages}"

[downloader.openlist]
url = "http://localhost:5244"
token = ""
offline_download_tool = "qBittorrent"

# ---------- 元数据 ----------
[metadata]
pipeline = ["regex", "tmdb"]
# ai_source = "primary"

[metadata.tmdb]
language = "zh-CN"

# ---------- AI source（可选） ----------
# [ai.sources.primary]
# type = "api"
# provider = "openai-compatible"
# api_key = "sk-xxx"
# base_url = "https://api.deepseek.com/v1"
# model = "deepseek-chat"

# ---------- 通知（可选） ----------
[notification]
enabled = false        # 设为 true 启用通知
batch_interval = 300.0 # 兼容字段；durable outbox 始终逐条发送，当前值会被忽略

# Telegram 通知（取消注释以启用）
# [[notification.bots]]
# type = "telegram"
# enabled = true
# config = { bot_token = "你的Bot Token", user_id = "你的用户ID" }

# PushPlus 微信通知（取消注释以启用）
# [[notification.bots]]
# type = "pushplus"
# enabled = true
# config = { user_token = "你的PushPlus Token", channel = "wechat" }
# channel 可选: wechat（微信）, webhook, cp（企业微信）, mail（邮件）

# ---------- AI 智能助理（可选） ----------
[assistant]
enabled = false   # 设为 true 启用助理

[assistant.telegram]
bot_token = ""        # Telegram Bot Token，从 @BotFather 获取
allowed_users = [123456789]  # 必填；只有这些用户可以使用 Assistant

# ---------- Bangumi（可选） ----------
[bangumi]
access_token = ""   # Bangumi API Token，也支持环境变量 BANGUMI_TOKEN

# ---------- Mikan（可选） ----------
[mikan]
username = ""   # Mikan 账号
password = ""   # Mikan 密码

# ---------- 日志 ----------
[log]
level = "INFO"           # 日志级别: DEBUG, INFO, WARNING, ERROR, CRITICAL
rotation = "00:00"       # 日志轮转时间
retention = "1 week"     # 旧日志保留时长
```

## 第三步：配置必填项与推荐项

以下是**最小必填配置**，让程序能够跑起来：

### 1. RSS 订阅链接

从 [Mikan Project](https://mikanani.me) 获取你的 RSS 订阅链接，填入 `rss.urls`：

```toml
[rss]
urls = ["https://mikanani.me/RSS/MyBangumi?token=你的token"]
```

### 2. Openlist 配置

确保你的 Openlist 已部署并开启了离线下载功能：

```toml
[downloader]
download_path = "/PikPak/Anime"         # 下载路径

[downloader.openlist]
url = "http://localhost:5244"
token = "你的令牌"
offline_download_tool = "qBittorrent"
```

> **令牌获取**：登录 Openlist 后台 → 设置 → 其他 → 令牌

### 3. 推荐：AI + TMDB

推荐配置 AI source 做标题解析，并继续使用 TMDB 做校验；如果不配置 source，主程序使用默认的 `regex` + `tmdb`。

```toml
[metadata]
pipeline = ["ai", "tmdb"]
ai_source = "primary"

[ai.sources.primary]
type = "api"
provider = "openai-compatible"
api_key = "sk-xxx"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
```

> API source 支持 OpenAI compatible 和 Anthropic Messages；也可把 source 配成 pi、claude-code 或 codex Agent。

## 第四步：启动主程序

```bash
openlist-ani
```

程序启动后会：
1. 按照 `interval_time` 间隔定期抓取 RSS
2. 发现新资源后通过 Openlist 离线下载
3. 下载完成后通过配置的 parser + validator 分析并重命名（推荐 LLM + TMDB，默认 regex + TMDB）

## 第五步（可选）：启用通知

### Telegram 通知

1. 向 [@BotFather](https://t.me/BotFather) 发送 `/newbot` 创建 Bot，获取 `bot_token`
2. 向 [@userinfobot](https://t.me/userinfobot) 发送消息获取你的 `user_id`
3. 配置：

```toml
[notification]
enabled = true

[[notification.bots]]
type = "telegram"
enabled = true
config = { bot_token = "123456:ABC-DEF...", user_id = "你的UserID" }
```

### PushPlus 微信通知

1. 前往 [PushPlus](https://pushplus.plus/) 注册获取 Token
2. 配置：

```toml
[notification]
enabled = true

[[notification.bots]]
type = "pushplus"
enabled = true
config = { user_token = "你的Token", channel = "wechat" }
```

## 第六步（可选）：启用 AI 智能助理

AI 助理通过 Telegram Bot 提供自然语言交互，可以让 AI 帮你搜索并下载番剧。

1. 再创建一个 Telegram Bot（或复用通知 Bot）
2. 配置：

```toml
[assistant]
enabled = true

[assistant.telegram]
bot_token = "你的Bot Token"
allowed_users = [123456789]   # 你的 Telegram 用户 ID
```

3. 启动助理（需单独运行）：

```bash
openlist-ani-assistant
```

> 内置 skills 会随程序包加载并自动更新；当前工作目录下的 `./skills` 只用于新增自定义 skill，或放置同名 skill 来覆盖内置版本。

> 主程序和助理需要**同时运行**。可以使用 `tmux`、`screen` 或 systemd 来管理。

> 助理支持两种运行模式：
> - **Telegram 模式**（默认）：通过 Telegram Bot 交互
> - **CLI 模式**：本地终端交互界面，添加 `--cli` 参数启动
>
> ```bash
> openlist-ani-assistant --cli          # 本地 CLI 模式
> ```

## 第七步（可选）：配置 Bangumi 和 Mikan，用于 Assistant 支持更多功能

### Bangumi 收藏同步

```toml
[bangumi]
access_token = "你的Bangumi Token"
```

> Token 获取方式：前往 [Bangumi 开发者页面](https://bgm.tv/dev/app) 创建应用并获取 Access Token。也可以通过环境变量 `BANGUMI_TOKEN` 设置。

### Mikan 账号集成

```toml
[mikan]
username = "你的Mikan用户名"
password = "你的Mikan密码"
```

## 后台运行

### 使用 systemd（推荐）

创建 `/etc/systemd/system/openlist-ani.service`：

```ini
[Unit]
Description=Openlist-Ani
After=network.target

[Service]
Type=simple
User=你的用户名
WorkingDirectory=/path/to/你的运行目录
ExecStart=/usr/local/bin/openlist-ani
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now openlist-ani
```

如需同时运行助理，创建类似的 service 文件将 `ExecStart` 改为 `openlist-ani-assistant`。

### 使用 tmux

```bash
tmux new-session -d -s oani 'openlist-ani'
tmux new-session -d -s oani-assistant 'openlist-ani-assistant'
```
