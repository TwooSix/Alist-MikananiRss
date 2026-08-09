# 配置说明

程序默认读取当前工作目录下的 `config.toml`。可通过环境变量 `CONFIG_PATH` 指定其他路径，例如 Docker 镜像中默认设置为 `CONFIG_PATH=/config.toml`。

## 完整配置示例
```toml
config_version = 2

[backend]
host = "127.0.0.1"  # Backend API bind address (127.0.0.1 = localhost only)
port = 26666  # Backend API listening port

[rss]
urls = []
interval_time = 300 # RSS fetch interval in seconds (default: 5 minutes)
strict = false  # Strict mode: only download entries that can be successfully renamed

[rss.filter]
exclude_patterns = []  # Regex patterns to exclude RSS entries by title
exclude_fansub = []
exclude_quality = []
exclude_languages = []

[rss.priority]
field_order = ["fansub", "quality", "languages"]
fansub = []
languages = []
quality = ["2160p", "1080p", "720p", "480p", "360p"]

[proxy]
http = ""  # HTTP proxy URL (e.g., "http://127.0.0.1:7890")
https = ""  # HTTPS proxy URL (e.g., "http://127.0.0.1:7890")

[downloader]
download_path = "/"
rename_format = "{anime_name} S{season:02d}E{episode:02d} {fansub} {quality} {languages}"

[downloader.openlist]
url = "http://localhost:5244"
token = ""
offline_download_tool = "qBittorrent"  # Supported tools, case-insensitive

[metadata]
pipeline = ["regex", "tmdb"]
# ai_source = "primary"  # Optional; first declared source is used by default

[metadata.tmdb]
# api_key = ""  # Built-in default key provided; only set this to override
language = "zh-CN"

# API source: Metadata calls the API directly; Assistant wraps it with Pi.
# [ai.sources.primary]
# type = "api"
# provider = "openai-compatible"  # or "anthropic-messages"
# api_key = "sk-xxx"
# model = "gpt-5-mini"
# base_url = "https://api.openai.com/v1"  # optional official default

# Agent source: executable/model are optional and use native agent config.
# [ai.sources.chat]
# type = "agent"
# agent = "pi"  # pi, claude-code, or codex
# executable = "pi"
# model = ""

[notification]
enabled = false  # Enable/disable notification system
batch_interval = 300.0  # 持久化聚合窗口（秒）；0 表示逐条立即发送

# Telegram bot configuration (optional)
# [[notification.bots]]
# type = "telegram"
# enabled = true
# config = { bot_token = "your_bot_token", user_id = "your_user_id" }

# PushPlus bot configuration (optional)
# [[notification.bots]]
# type = "pushplus"
# enabled = true
# config = { user_token = "your_user_token", channel = "wechat" }  # channel: wechat, webhook, cp, mail

# WeChat iLink bot notification (optional)
# [[notification.bots]]
# type = "wechat"
# enabled = true
# config = { account_id = "bot@im.bot", token = "your_bot_token", base_url = "https://ilinkai.weixin.qq.com", home_channel = "user@im.wechat" }

# Feishu/Lark bot notification (optional)
# [[notification.bots]]
# type = "feishu"
# enabled = true
# config = { app_id = "cli_xxx", app_secret = "your_app_secret" }

[assistant]
enabled = false  # Enable/disable assistant module
# backend = "primary"  # Optional; first declared source is used by default
# skills_dir = "skills"  # Pi/Claude direct-load compatibility path

# Telegram assistant configuration (optional)
[assistant.telegram]
enabled = false
bot_token = ""  # Telegram bot token from @BotFather
allowed_users = [123456789]  # Required; Telegram user IDs allowed to use Assistant

[assistant.wechat]
enabled = false
account_id = ""
token = ""
base_url = "https://ilinkai.weixin.qq.com"
home_channel = ""
allowed_users = ["user@im.wechat"]
dm_policy = "open"

[assistant.feishu]
enabled = false
app_id = ""
app_secret = ""
domain = "feishu"
connection_mode = "websocket"
webhook_host = "127.0.0.1"  # 仅 connection_mode = "webhook" 时使用
webhook_port = 8765         # 仅 connection_mode = "webhook" 时使用
webhook_path = "/feishu/webhook"  # 仅 connection_mode = "webhook" 时使用
bot_open_id = ""
require_mention = true
state_dir = "data/messaging"
allowed_users = ["ou_xxx"]

[bangumi]
access_token = ""  # Bangumi API Access Token (also supports env var BANGUMI_TOKEN)

[mikan]
username = ""  # Mikan (mikanani.me) account username
password = ""  # Mikan account password

[log]
level = "INFO"  # Log level: DEBUG, INFO, WARNING, ERROR, CRITICAL
rotation = "00:00"  # Log rotation: time-based "00:00" (midnight)
retention = "1 week"  # How long to keep old logs: "1 week", "30 days", "3 months", etc.
```

## 配置说明

以下为 `config.toml` 的各字段配置说明。

### Backend（后端 API）

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `host` | string | `"127.0.0.1"` | 后端 API 绑定地址 |
| `port` | int | `26666` | 后端 API 监听端口 |

### RSS

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `urls` | list | `[]` | RSS 订阅链接列表 |
| `interval_time` | int | `300` | RSS 抓取间隔（秒） |
| `strict` | bool | `false` | 严格模式：仅下载能成功重命名的条目（需配合 `rename_format` 使用） |

#### rss.filter（过滤与黑名单）

基于正则表达式和元数据解析器解析出的字段（字幕组、清晰度、语言）进行过滤。匹配的资源将被排除。

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `exclude_patterns` | list | `[]` | 正则排除模式列表。匹配任一正则的 RSS 条目将被排除（不下载）。使用 `re.search()` 部分匹配 |
| `exclude_fansub` | list | `[]` | 排除的字幕组列表（精确匹配），如 `["XX字幕组", "YY字幕组"]` |
| `exclude_quality` | list | `[]` | 排除的清晰度列表（精确匹配），如 `["480p"]` |
| `exclude_languages` | list | `[]` | 排除的语言列表。资源的任一语言命中即排除。可选值：`"简"`、`"繁"`、`"日"`、`"英"`、`"未知"` |

**示例：**

```toml
[rss.filter]
exclude_patterns = ["合集", "SP\\d+"]  # 排除标题含「合集」或「SP+数字」的条目
exclude_fansub = ["XX字幕组"]  # 排除指定字幕组
exclude_quality = ["480p"]     # 排除 480p 资源
exclude_languages = ["未知"]   # 排除语言未知的资源
```

#### rss.priority（下载优先级）

当同一番剧同一集存在多个资源时，根据优先级规则自动过滤低优先级资源。高优先级资源已下载后，低优先级资源将被跳过。`version` 字段不受限制：更高版本始终会下载。

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `field_order` | list | `["fansub", "quality", "languages"]` | 字段比较优先级顺序（靠前优先级高） |
| `fansub` | list | `[]` | 字幕组优先级列表（靠前优先级高） |
| `languages` | list | `[]` | 语言优先级列表（靠前优先级高）。单语言：`"简"`、`"繁"`、`"日"`、`"英"`；组合语言：`"简繁"`（简繁双语）等 |
| `quality` | list | `["2160p", "1080p", "720p", "480p", "360p"]` | 清晰度优先级列表（默认高清优先）。设为 `[]` 禁用清晰度过滤 |

**优先级判断逻辑：**

1. **按 `field_order` 顺序逐字段比较**：第一个产生差异的字段直接决定结果
   - 候选资源在该字段优先级更高 → 允许下载
   - 候选资源在该字段优先级更低 → 跳过
   - 优先级相等 → 继续检查下一个字段
2. **所有字段优先级相等** → 允许下载
3. **version 旁路**：同一番剧/季/集/字幕组/语言下，若候选 version 更高（字幕组纠错后发布的新版），始终允许下载

**示例：**

```toml
[rss.priority]
field_order = ["fansub", "quality", "languages"]  # 字幕组 > 清晰度 > 语言
fansub = ["Fansub_A", "Fansub_B"]  # Fansub_A > Fansub_B > 其他
languages = ["简", "简繁", "繁"]   # 纯简体 > 简繁双语 > 纯繁体 > 其他
quality = ["2160p", "1080p", "720p", "480p", "360p"]
```

在同番剧，同季度，同集数的情况下，存在多个候选项，则逐步检查 字幕组->清晰度->语言：

1. 若已下载了优先级更高的字幕组（Fansub_A），则所有非 Fansub_A 的字幕组资源均会跳过下载，若已下载了第二优先级的字幕组（Fansub_B），则后续只有Fansub_B和Fansub_A的资源允许被下载。允许被下载的资源，会继续比较下一个字段quality
2. 以相同的逻辑，比较清晰度的优先级，`["2160p", "1080p", "720p", "480p", "360p"]` 意为优先下载清晰度更高的资源。允许被下载的资源，会继续比较下一个字段languages
3. 以相同的逻辑，比较字幕语言的优先级，`["简", "简繁", "繁"]` 意为优先下载纯简体的资源。

**语言组合匹配规则：**

语言优先级支持「精确匹配」和「包含匹配」两种模式，精确匹配优先级更高：

- **精确匹配**：将资源的语言列表排序后拼接为字符串（如 `[CHS, CHT]` → `"简繁"`），与配置项精确比较
- **包含匹配（兜底）**：若无精确匹配，则检查资源的语言字符串是否包含配置中的单字符条目

如，若优先级只设置了["简"]，但实际资源语言为"简繁"时，会先优先搜索配置项是否包含"简繁"，若无，则fallback归纳为"简"，和简体资源优先级同级。若优先级设置为["简", "简繁"], 则当已有纯简体资源下载过时，简繁不会被下载。

### Proxy（代理）

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `http` | string | `""` | HTTP 代理地址（如 `http://127.0.0.1:7890`） |
| `https` | string | `""` | HTTPS 代理地址 |

### Downloader 与 OpenList

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `downloader.download_path` | string | `"/"` | 下载保存路径 |
| `downloader.rename_format` | string | 见下方 | 与 downloader 实现绑定的重命名格式模板 |
| `downloader.openlist.url` | string | `"http://localhost:5244"` | OpenList 访问地址 |
| `downloader.openlist.token` | string | `""` | 令牌，见「设置 → 其他 → 令牌」 |
| `downloader.openlist.offline_download_tool` | string | `"qBittorrent"` | 离线下载工具（不区分大小写）。可选值：`aria2`、`qBittorrent`、`PikPak`、`115 Cloud`、`115 Open`、`123Pan`、`123 Open`、`SimpleHttp`、`Thunder`、`ThunderBrowser`、`ThunderX`、`Transmission` |

#### 重命名格式

默认格式：`{anime_name} S{season:02d}E{episode:02d} {fansub} {quality} {languages}`

支持的占位符：
- `{anime_name}` — 番剧名
- `{season}` — 季度（`:02d` 表示两位数字补零）
- `{episode}` — 集数
- `{year}` — TMDB 剧集条目的首播年份；TMDB 无日期或降级失败时为空
- `{fansub}` — 字幕组
- `{quality}` — 画质
- `{languages}` — 语言

### Metadata pipeline

`metadata.pipeline` 是有序步骤列表。未配置 AI source 时默认使用 `["regex", "tmdb"]`；需要 AI 提取时设置为 `["ai", "tmdb"]`。`metadata.ai_source` 只控制其中的 `ai` 步骤，省略时选择第一个声明的 source。设置了 `ai_source` 但 pipeline 不包含 `ai` 时仅告警。

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `pipeline` | list | 自动选择 | 支持 `regex`、`ai`、`tmdb`，按声明顺序执行 |
| `ai_source` | string | 第一个 source | `ai` 步骤使用的 `[ai.sources.<名称>]` |
| `tmdb.api_key` | string | 内置默认值 | TMDB API Key |
| `tmdb.language` | string | `"zh-CN"` | TMDB 元数据语言 |

Agent source 的 Metadata 调用是无工具、无历史的一次性会话。输出必须满足结构化 JSON 约束；非法输出会修复一次，仍失败则由现有 pipeline fallback 继续处理。

### AI sources

配置头固定为 `[ai.sources.<名称>]`，可以同时声明多个 source，不使用 profile 或数组。`metadata.ai_source` 和 `assistant.backend` 可以独立选择；二者省略时都选择第一个声明项，不做隐式故障转移。

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `type` | string | 必填 | `api` 或 `agent` |
| `provider` | string | API 必填 | `openai-compatible` 或 `anthropic-messages` |
| `api_key` | string | API 必填 | API 凭据，不会写入日志 |
| `base_url` | string | 官方地址 | OpenAI 默认 `https://api.openai.com/v1`；Anthropic 默认 `https://api.anthropic.com` |
| `model` | string | API 必填 | API source 的模型；Agent source 可省略以使用原生配置 |
| `agent` | string | Agent 必填 | 内置 `pi`、`claude-code`、`codex`，或已安装 entry point 的名称 |
| `executable` | string | Agent 默认命令 | 自定义 Agent 可执行文件路径 |

API source 在 Metadata 中直接调用 API，在 Assistant 中始终由内置 Pi 注入 provider 配置。Agent source 在 Metadata 中运行隔离会话，在 Assistant 中调用对应 Agent 的会话接口。完全没有 `[ai.sources]` 时，Assistant 使用 Pi 原生认证和模型配置；Metadata 仅在显式包含 `ai` 时才尝试 Pi。

Pi 的 `executable` 解析顺序为：source 显式配置、`OPENLIST_ANI_PI_EXECUTABLE`、PATH 中已有的 `pi`、程序托管的锁定版本。前面三项均不存在时，程序按当前操作系统和 CPU 下载 Pi 官方独立包，通过官方 `SHA256SUMS` 校验后原子安装到配置文件旁的 `data/assistant/runtime/pi/<版本>/`。安装有跨进程锁，不依赖 Node.js/npm，也不会修改配置文件或覆盖用户已有 Pi。只读目录、网络或校验失败时启动会给出可操作错误，不会运行未校验或半安装的文件。

### 自动配置迁移

`config_version` 当前为 `2`。没有版本号的历史配置按 v1 处理：启动时先获取迁移锁，在原目录生成逐字节备份 `config.toml.bak.v1.<时间>`，再连续执行版本迁移、Pydantic 校验和原子替换。成功迁移一次后不会重复备份。只读挂载无法备份时不会覆盖原文件，而是使用内存迁移结果启动并持续告警。

v1 的 `[llm]`、`[metadata_parser]`、`[metadata_validator]`、`[openlist]` 和 `[file_renamer]` 会分别迁移到 `[ai.sources.legacy-llm]`、`[metadata]` 和 `[downloader]`。新旧字段同时存在时新字段优先，旧字段仅补全缺失值。

### Notification（通知）

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `false` | 是否启用通知系统 |
| `batch_interval` | float | `300.0` | 持久化聚合窗口（秒）；从最早待发项开始计时，`0` 表示逐条立即发送，不能为负数 |

通知批次保存在 SQLite outbox 中，重启不会丢失。不同渠道独立记录成功与重试状态；批次超过渠道安全长度时会按完整条目拆成尽可能少的消息。

#### Telegram 通知

```toml
[[notification.bots]]
type = "telegram"
enabled = true
config = { bot_token = "your_bot_token", user_id = "your_user_id" }
```

#### PushPlus 通知

```toml
[[notification.bots]]
type = "pushplus"
enabled = true
config = { user_token = "your_user_token", channel = "wechat" }
# channel 可选: wechat, webhook, cp, mail
```

#### 微信 ClawBot 通知

```toml
[[notification.bots]]
type = "wechat"
enabled = true
config = { account_id = "bot@im.bot", token = "your_bot_token", base_url = "https://ilinkai.weixin.qq.com", home_channel = "user@im.wechat" }
```

1. 先执行 setup 命令：

```bash
uv run openlist-ani-wechat-login
```

2. 终端会打印二维码。用微信扫码并确认登录。
3. 登录成功后，命令会继续阻塞等待你给机器人发送任意一条文本消息，用于捕获 `chat_id`。
4. 命令最后会在终端打印完整 TOML 配置块, 复制进 `config.toml`，再启动 `openlist-ani` 或 `openlist-ani-assistant`。

#### 飞书通知

```toml
[[notification.bots]]
type = "feishu"
enabled = true
config = { app_id = "cli_xxx", app_secret = "your_app_secret" }
```

飞书通知需要先通过飞书助理绑定目标会话：

1. 在飞书开放平台创建自建应用，启用机器人能力。
2. 在「凭证与基础信息」复制 `App ID` 和 `App Secret`，填入通知和助理配置。
3. 启动 `openlist-ani-assistant`，在要接收通知的私聊中发送 `/set-notify-home`；如果是群聊，请先 @机器人 再发送该命令。
4. 绑定完成后，后续通知会发送到该会话。

### Assistant（智能助理）

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `false` | 是否启用助理模块 |
| `backend` | string | 第一个 source | Assistant 使用的 `[ai.sources.<名称>]`；API source 会自动交给 Pi |
| `skills_dir` | string | `"skills"` | 用户自定义 Skills 目录；Pi 通过 `--skill`、Claude Code 通过 `--plugin-dir` 直接加载，不复制到会话目录 |

Assistant 不再实现自己的模型循环、上下文压缩、subagent、memory consolidation
或 Skill 索引。内置 Skills 打包为同一份标准 Agent 插件：Pi 直接接收 `--skill`
目录，Claude Code 直接接收 `--plugin-dir`，Codex 首次使用时通过自己的
`codex plugin marketplace add`/`codex plugin add` 注册并由 Codex 管理缓存。
OAni 不再向临时会话目录复制或链接 Skills，也不读取 `SKILL.md` 建立第二份目录。

`skills_dir` 保留用于兼容已有自定义 Skills：Pi 会直接传入整个目录；Claude
Code 会将其中的 Skill 目录作为本地插件参数传入。Codex 当前没有等价的临时
目录参数，因此 Codex 用户的额外 Skills 应安装到 Codex 原生插件或
`.agents/skills` 位置；`skills_dir` 不会注入 Codex。脚本均在本地运行。
Telegram、微信和飞书启用时必须配置非空 `allowed_users`。

#### Telegram 助理

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `false` | 是否启用 Telegram 助理 |
| `bot_token` | string | `""` | Telegram Bot Token（从 @BotFather 获取） |
| `allowed_users` | list | 无 | 必填；允许使用 Assistant 的用户 ID，空列表会阻止启动 |

#### 微信 iLink 助理

```toml
[assistant]
enabled = true

[assistant.wechat]
enabled = true
account_id = "bot@im.bot"
token = "your_bot_token"
base_url = "https://ilinkai.weixin.qq.com"
home_channel = "user@im.wechat"
allowed_users = ["user@im.wechat"]
```

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `false` | 是否启用微信 iLink 助理前端 |
| `account_id` | string | `""` | iLink Bot account ID；由 `openlist-ani-wechat-login` 打印 |
| `token` | string | `""` | iLink Bot token；由 `openlist-ani-wechat-login` 打印 |
| `base_url` | string | `"https://ilinkai.weixin.qq.com"` | iLink API 地址 |
| `home_channel` | string | `""` | 允许微信助理交互的唯一会话；由 `openlist-ani-wechat-login` 捕获首条消息后打印 |
| `allowed_users` | list | 无 | 必填；允许使用 Assistant 的微信发送者 ID，空列表会阻止启动 |
| `dm_policy` | string | `"open"` | 私聊访问策略，当前文本实现保留该配置 |

微信助理启动前也需要先执行 `openlist-ani-wechat-login`，并把打印出的 `account_id/token/base_url/home_channel` 填入配置。

#### 飞书 / Lark 助理

```toml
[assistant]
enabled = true

[assistant.feishu]
enabled = true
app_id = "cli_xxx"
app_secret = "your_app_secret"
```

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enabled` | bool | `false` | 是否启用飞书助理前端 |
| `app_id` | string | `""` | 自建应用 App ID，飞书开放平台「凭证与基础信息」获取 |
| `app_secret` | string | `""` | 自建应用 App Secret，飞书开放平台「凭证与基础信息」获取 |
| `domain` | string | `"feishu"` | `feishu` 或 `lark` |
| `connection_mode` | string | `"websocket"` | 连接方式，保持默认即可；需要自建回调服务时可改为 `webhook` |
| `webhook_host` | string | `"127.0.0.1"` | 使用 `webhook` 时的监听地址 |
| `webhook_port` | int | `8765` | 使用 `webhook` 时的监听端口 |
| `webhook_path` | string | `"/feishu/webhook"` | 使用 `webhook` 时的请求路径 |
| `bot_open_id` | string | `""` | 可选；用于更精确地判断群聊 @机器人 |
| `require_mention` | bool | `true` | 群聊中是否必须 @机器人 才处理 |
| `state_dir` | string | `"data/messaging"` | `/set-notify-home` 通知目标保存目录 |
| `allowed_users` | list | 无 | 必填；允许交互的飞书用户 ID，空列表会阻止启动 |

在开放平台启用机器人和接收消息事件后，把机器人加入目标私聊或群聊，然后启动助理。私聊中可直接发送消息；群聊中请 @机器人发送消息。需要接收通知时，在目标会话发送 `/set-notify-home` 完成绑定。

### Bangumi

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `access_token` | string | `""` | Bangumi API Access Token（也支持环境变量 `BANGUMI_TOKEN`） |

### Mikan

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `username` | string | `""` | Mikan 账号用户名 |
| `password` | string | `""` | Mikan 账号密码 |

### Log（日志）

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `level` | string | `"INFO"` | 日志级别（DEBUG / INFO / WARNING / ERROR / CRITICAL） |
| `rotation` | string | `"00:00"` | 日志轮转时间 |
| `retention` | string | `"1 week"` | 旧日志保留时长（如 `"1 week"`、`"30 days"`） |
