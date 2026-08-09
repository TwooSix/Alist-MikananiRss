# 快速开始

## 📋 准备工作

1. 参照 [Openlist 官方文档](https://doc.oplist.org/guide) 部署 Openlist，并搭建好离线下载
2. 准备好 RSS 订阅链接（如 [Mikan Project](https://mikanani.me)）
3. 可选：准备 AI API Key，或安装并登录 Pi / Claude Code / Codex Agent（均未配置时元数据使用本地正则 + TMDB）

非 Docker 安装不需要手工安装 Pi 或 Node.js。首次启动 Assistant 时，程序会
自动下载当前版本锁定的官方 Pi 独立包、校验 SHA-256，并安装到持久化 runtime
目录。已有的 Pi 或显式配置的 `executable` 会直接复用。Windows 缺少 Bash 时，
程序会以同样方式准备经过固定 SHA-256 校验的官方 PortableGit，不修改系统安装
或全局 PATH。Docker 镜像已预装 Pi，并使用镜像内的 Bash。

## 🚀 安装与启动

### 方式一：PIP 安装（推荐）

**1. 安装**

```bash
pip install openlist-ani
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

[downloader.openlist]
url = "http://localhost:5244"
token = ""
offline_download_tool = "qBittorrent"

[metadata]
pipeline = ["regex", "tmdb"]

# 可选：启用 AI Metadata；Assistant 会通过内置 Pi 使用此 API。
# [ai.sources.primary]
# type = "api"
# provider = "openai-compatible"
# api_key = "sk-xxx"
# base_url = "https://api.deepseek.com/v1"
# model = "deepseek-chat"
# 推荐把 metadata.pipeline 改为 ["ai", "tmdb"]
```

> 完整配置项请参考 [配置说明](configuration)

**3. 启动**

```bash
openlist-ani
```

**4.（可选）启动 AI 助理**

在配置文件中补充助理配置后运行：

```toml
[assistant]
enabled = true

[assistant.telegram]
bot_token = ""        # 从 @BotFather 获取
allowed_users = [123456789]  # 必填；只有这些用户可以使用 Assistant
```

```bash
openlist-ani-assistant
```

### 方式二：Docker 部署

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
> 使用 `--network host` 模式，配置文件和本机运行完全一致。
> 如需启用 AI 助理，填写好配置后将 `ENABLE_ASSISTANT` 设为 `true`。
> 详细说明见 [Docker 部署指南](docker-deployment)。

### 方式三：从源码编译

#### 前置：安装 uv

**Linux / macOS**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Windows**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

> 更多安装方式参考 [uv 官方文档](https://github.com/astral-sh/uv)

#### 步骤

```bash
# 1. 克隆仓库
git clone https://github.com/TwooSix/Openlist-Ani.git && cd Openlist-Ani

# 2. 切换到最新 Release tag（master 为开发分支，不保证稳定）
# Release 版本以 tag 为准，不需要存在同名 branch
git fetch --tags
git checkout tags/v***    # 将 v*** 替换为 Release 页面中的版本号

# 3. 安装依赖
uv sync --no-dev --frozen

# 4. 创建 config.toml 并填写配置（内容同上）

# 5. 启动
uv run openlist-ani

# 6.（可选）启动 AI 助理
uv run openlist-ani-assistant
```
