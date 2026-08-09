<p align="center">
  <img src="imgs/logo.png" alt="Openlist-Ani Logo" width="420" />
</p>

<h1 align="center">Openlist-Ani</h1>

<p align="center">
  <b>🎬 RSS 订阅 → 自动下载 → AI 重命名，一站式番剧自动化管理</b>
</p>

<p align="center">
  Openlist-Ani，简称O-Ani，从动漫番剧相关的 RSS 订阅源中自动获取番剧更新，通过 Openlist 离线下载至对应网盘，<br/>
  并结合 LLM 分析资源名，将资源重命名为 Emby / Jellyfin 可解析的格式。
</p>

---

## ✨ 特点

- 📡 **自动追番** — 自动获取 RSS 番剧更新并下载
- 📦 **多网盘支持** — 基于OpenList实现，支持 PikPak、115 等离线下载
- 🤖 **AI 重命名** — AI 分析资源名 + TMDB 搜索，精准获取番剧名、季度、集数
- 💬 **智能助理** — 挂载至 Telegram / 微信ClawBot / 飞书机器人，通过自然语言让 AI 帮你搜索并下载资源
- 🔔 **更新通知** — 通过 PushPlus、Telegram、微信ClawBot、飞书等渠道推送更新

## 📋 准备工作

1. 参照 [Openlist 官方文档](https://doc.oplist.org/guide) 部署 Openlist，并搭建好离线下载
2. 准备好 RSS 订阅链接（如 [Mikan Project](https://mikanani.me)）
3. 可选：准备 AI API Key，或安装并登录 Pi / Claude Code / Codex Agent（均未配置时元数据使用本地正则 + TMDB）

源码或 PIP 安装无需 Node.js/npm。首次使用默认 Pi Assistant 时，程序会下载
官方锁定版本的独立二进制，校验 SHA-256 后原子安装到配置文件旁的
`data/assistant/runtime/pi/`。显式配置的 `executable` 和 PATH 中已有的 Pi
仍然优先，不会被覆盖。Windows 如果没有可用的 Bash，程序还会下载官方
PortableGit、校验固定 SHA-256，并将 Git Bash 安装到
`data/assistant/runtime/git-bash/`；不会修改系统安装或全局 PATH。

API source（包括旧 `[llm]` 自动迁移得到的 source）会自动注入 Pi，无需重新
配置模型；完全没有 AI source 时才使用 Pi 自己的登录和模型配置。Docker 镜像
已预装 Pi。如果使用 Claude Code 或 Codex source，则安装并登录对应的原生 CLI。
内置 Skills 不再复制到临时会话目录：Pi 直接使用 `--skill`，Claude Code 使用
`--plugin-dir`，Codex 在首次会话时通过自己的插件管理器注册随包插件。

## 🚀 快速开始

<details open>
<summary><b>方式一：源码安装（推荐）</b></summary>

#### 前置：安装 uv

<table><tr><td>

**Linux / macOS**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

</td><td>

**Windows**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

</td></tr></table>

> 更多安装方式参考 [uv 官方文档](https://github.com/astral-sh/uv)

**1. 安装**

```bash
git clone https://github.com/TwooSix/Openlist-Ani.git
cd Openlist-Ani

# 推荐切换到最新 Release tag；master 为开发分支，不保证稳定
# Release 版本以 tag 为准
git fetch --tags
git checkout tags/v***    # 将 v*** 替换为 Release 页面中的版本号

uv sync --no-dev --frozen
```

**2. 创建配置文件**

在运行目录下新建 `config.toml`，填入以下内容：

```toml
config_version = 2

[rss]
urls = ["RSS订阅链接"]

[downloader]
download_path = "/PikPak/Anime"
rename_format = "{anime_name} S{season:02d}E{episode:02d} {fansub} {quality} {languages}"
# 可选年份："{anime_name} ({year}) S{season:02d}E{episode:02d}"

[downloader.openlist]
url = "http://localhost:5244"
token = ""                          # 令牌，见「设置 → 其他 → 令牌」
offline_download_tool = "qBittorrent"

[metadata]
pipeline = ["regex", "tmdb"]       # 默认配置；推荐配置 AI source 后改为 ["ai", "tmdb"]

# 可选：API source。Metadata 直接调用 API，Assistant 由内置 Pi 承载。
# [ai.sources.primary]
# type = "api"
# provider = "openai-compatible"
# api_key = "sk-xxx"
# base_url = "https://api.deepseek.com/v1"
# model = "deepseek-chat"
```

> 完整配置项请参考 [`config.toml.example`](config.toml.example) 及 [配置说明](https://github.com/TwooSix/Openlist-Ani/wiki/configuration)

**3. 启动**

```bash
uv run openlist-ani
```

**4.（可选）启动 AI 助理**

在配置文件中补充助理配置后运行：

```toml
[assistant]
enabled = true

[assistant.telegram]
enabled = true
bot_token = ""        # 从 @BotFather 获取
allowed_users = [123456789]  # 必填；只有这些用户可以使用 Assistant
```

```bash
uv run openlist-ani-assistant
```

内置 Skills 会随程序包加载并由 Agent 原生发现。`./skills` 可向 Pi/Claude Code
直接提供自定义 Skills；Codex 的额外 Skills 请使用 Codex 原生插件或
`.agents/skills` 目录。

</details>

<details>
<summary><b>方式二：Docker 部署</b></summary>

**1. 准备文件**

在运行目录下创建：
- `config.toml` — 配置文件（内容同上）
- `data/` — 数据目录

**2. 启动容器**

```bash
docker run -d \
  --name openlist-ani \
  --network host \
  -e ENABLE_ASSISTANT=false \
  -v /path/to/config.toml:/config.toml \
  -v /path/to/data:/data \
  twosix26/openlist-ani:latest
```

> 将 `/path/to/` 替换为你的实际路径。  
> 如需启用 AI 助理，填写好配置后将 `ENABLE_ASSISTANT` 设为 `true`。  
> 详细说明见 [Docker 部署指南](https://github.com/TwooSix/Openlist-Ani/wiki/docker-deployment)。

</details>

<details>
<summary><b>方式三：PIP 安装</b></summary>

```bash
pip install openlist-ani
openlist-ani

# 可选：启动 AI 助理
openlist-ani-assistant
```

</details>

## 📖 文档

- [快速开始](https://github.com/TwooSix/Openlist-Ani/wiki/quick-start)
- [PIP 安装指南](https://github.com/TwooSix/Openlist-Ani/wiki/pip-installation)
- [Docker 部署指南](https://github.com/TwooSix/Openlist-Ani/wiki/docker-deployment)
- [源码编译指南](https://github.com/TwooSix/Openlist-Ani/wiki/build-from-source)
- [配置说明](https://github.com/TwooSix/Openlist-Ani/wiki/configuration)

## 🖼️ 效果展示

| 重命名结果 | 智能助理 |
| :---: | :---: |
| <img src="https://github.com/TwooSix/Openlist-Ani/blob/master/imgs/show_pic1.png" width="400"/> | <img src="https://github.com/TwooSix/Openlist-Ani/blob/master/imgs/show_pic2.jpg" width="150"/> |
