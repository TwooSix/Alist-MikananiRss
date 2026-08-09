# Agent 架构 E2E 验收记录

验收时间：2026-08-06（Asia/Shanghai）

本文只记录脱敏结果，不包含服务器地址、RSS URL、API Key、Bot Token、OpenList Token、SSH 私钥或 Agent 登录信息。

## 本轮环境

- Linux 远程主机，Python 3.11。
- Pi 0.82.1（OpenList-Ani 托管运行时）。
- Claude Code 2.1.222，使用配置文件中的 OpenAI-compatible source 转换为 Anthropic-compatible 网关配置和模型。
- Codex CLI 0.145.0，使用原生登录。
- 真实 OpenList-Ani Backend 监听本机回环地址；Agent 仅执行只读 Skill 脚本。

## 真实业务流程

| 检查项 | 结果 | 说明 |
|---|---|---|
| 配置迁移与 v2 source 选择 | 通过 | 旧 `[llm]` 已迁移为命名 API source，Metadata 与 Assistant 可独立选择 source |
| 真实 RSS 获取 | 通过 | 从已配置 RSS 获取 9 个候选 |
| RSS → Agent Metadata | 通过 | Codex 一次性无工具会话完成 AI Metadata 提取 |
| Metadata 字段 | 通过 | anime name、season、episode、fansub、quality、languages 均满足最小完整性 |
| Metadata provenance | 通过 | 持久化结果包含 `ai`、`mikan`、`tmdb` 来源 |
| 任务持久化 | 通过 | 临时数据库中的任务从 Metadata 步骤推进到 download/pending |
| 生产数据安全 | 通过 | 使用临时配置副本和临时数据库，未启动下载 worker，未创建下载或订阅 |

## Assistant backend

| Backend | Skill 发现与脚本 | 流式事件 | 多轮上下文 | 结果 |
|---|---:|---:|---:|---|
| Pi | 原生 `--skill`；通过 | 产生 Skill、脚本、文本和完成事件 | RPC 会话恢复通过 | 通过 |
| Claude Code | 原生 `--plugin-dir`；通过 | 产生脚本、文本和完成事件 | 原生 session resume 通过 | 通过 |
| Codex | 项目 `.agents/skills`；通过 | 产生脚本、文本和完成事件 | 原生 thread resume 通过 | 通过 |

Pi 和 Codex 均完成 `list_rss.py`、`parse_rss.py` 的组合只读流程。Claude Code 使用相同 plugin 完成组合流程；配置的模型在该复合任务中耗时约 127 秒，并在 3 次工具错误后自行纠错，最终成功。为了单独验证 Adapter，另以 `list_rss.py` 完成了流式事件和第二轮 session resume 验收。

Codex 不支持临时传入任意 Skill 目录，因此 Adapter 将同一套内置/用户 Skills 暴露在每个会话工作目录的 `.agents/skills` 下；本轮真实 Codex 会话确认该发现方式有效。用户同名 Skill 仍覆盖内置 Skill。

Claude Code 在 root 用户下禁止 `bypassPermissions`。Adapter 已统一改用 Claude 的 `auto` 权限模式；真实 root 会话确认原生 plugin、只读 shell 脚本和上下文恢复均可工作。

## Metadata source

使用固定的虚构标题分别调用三条结构化提取路径，验证 JSON 中的 anime name、season、episode 和 quality：

| Source 路径 | 工具/历史隔离 | 结构校验 | 结果 |
|---|---:|---:|---|
| API source 直连 | 是 | 通过 | 通过 |
| Claude Code agent source | 是 | 通过 | 通过 |
| Codex agent source | 是 | 通过 | 通过 |

Agent Metadata 每次使用全新临时工作目录，不加载 Assistant Skills，不复用聊天历史。真实 RSS 持久化流程另行覆盖了 Codex Agent Metadata 与现有 fallback/pipeline 的组合。

## 自动测试

- 本地：`366 passed`，Ruff 全部通过。
- 远程：`366 passed`，Ruff 全部通过。
- 覆盖 Pi/Claude/Codex Adapter、API → Pi、Skill 目录/插件加载、事件映射、会话恢复、Metadata 隔离、配置迁移和旧 Tool/MCP 架构边界。

## 未纳入本轮的外部入口

本轮目标是验证所有 Agent backend 和真实业务链路，没有向 Telegram、飞书或微信测试账号发送消息。平台消息格式、白名单、排队、取消、确认和分段行为由自动测试覆盖；如需做真实聊天平台验收，应使用专用测试账号和非生产群组，避免向真实用户发送测试消息。
