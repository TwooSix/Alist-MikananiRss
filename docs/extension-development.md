# 核心扩展开发指南

业务扩展仅作为仓库内置 adapter 提交。新增实现后在
`bootstrap/backend.py` 的 `_build_registry` 显式注册，启动时若名称重复会立即失败。
Agent harness 是唯一例外，可以通过明确的 Python entry point 安装，不需要
修改前端、Metadata pipeline 或 Skill 系统。

## Agent Adapter

新 Agent 继承 `openlist_ani.assistant.harness.adapters.AgentAdapter`，实现
`open_session()` 和 `run_structured()`，并在扩展包中声明：

```toml
[project.entry-points."openlist_ani.agent_adapters"]
example = "example_package:ExampleAgentAdapter"
```

Adapter 只负责原生进程协议、会话恢复、事件转换以及该 Agent 的原生 Skill
入口。Pi 使用 `--skill`，Claude Code 使用 `--plugin-dir`，Codex 使用自身的
`codex plugin` 注册流程；不得复制或链接 Skill 到临时会话目录，也不得将
`SKILL.md` 正文拼进 system prompt、重新引入 OAni Tool Registry 或模型循环。
新 Agent 如支持临时目录参数，实现 `session_arguments()`；如必须通过原生插件
管理器配置，实现 `ensure_native_skills()`。

## RSS 来源

实现 `FeedAdapter`。特定域名 adapter 要先注册，通用 fallback 最后注册。

```python
class ExampleFeedAdapter:
    name = "example"

    def supports(self, url: str) -> bool:
        return "feeds.example.com" in url

    async def fetch(self, url, *, etag=None, last_modified=None):
        # 使用组合根传入的共享 aiohttp session。
        # 304 时 candidates 为空并设置 not_modified=True。
        return FeedFetchResult(
            candidates=[ReleaseCandidate.create(
                source_name=self.name,
                source_url=url,
                title="Example 01",
                download_url="magnet:...",
                guid="stable-entry-id",
            )],
            etag='"v2"',
        )
```

合同要求：`supports` 无网络副作用；网络错误向外抛出以触发该订阅退避；同一 RSS 项必须生成稳定 identity；单条解析失败可以跳过，但不能把整次网络失败伪装为空结果。

## 元数据来源

实现 `MetadataProvider`。标题解析器使用 `MetadataPhase.TITLE`，其他网站使用 `ENRICHMENT`。provider 必须返回与输入等长且同序的结果。

```python
class ExampleMetadataProvider:
    name = "example-metadata"
    phase = MetadataPhase.ENRICHMENT

    async def enrich_many(self, candidates, documents, attempt_counts):
        output = []
        for document in documents:
            document.apply(MetadataPatch(
                source=self.name,
                authoritative=True,
                priority=30,
                values=ReleaseMetadata(external_ids={"example": "123"}),
            ))
            output.append(MetadataResolution(document=document))
        return output

    async def close(self):
        pass
```

临时超时填 `retryable_error`，确定的无效响应填 `permanent_error`。没有可靠值时保留 `None`/空集合；`VideoQuality.UNKNOWN`、`LanguageType.UNKNOWN` 以及 feed 模型为兼容旧接口而产生的默认 v1 都不能声称是网站提供的结构化字段。`MetadataDocument.apply()` 会自动记录生效值、旧值和覆盖标记。不要修改候选项的标题、下载链接、来源或幂等键。新增字段必须同时定义序列化、证据合并和迁移兼容测试。

在新配置中可按顺序启用：

```toml
[metadata]
pipeline = ["regex", "example-metadata", "tmdb"]
```

历史配置会在启动时先备份，再迁移为当前 `metadata.pipeline` 结构；扩展只需面向当前配置版本。

## 下载后端与 Organizer

下载后端实现 `DownloadAdapter.start_or_resume`，并在每次具有外部副作用的状态变化后调用 `checkpoint_callback`：

```python
class ExampleDownloadAdapter:
    name = "example"

    async def start_or_resume(self, job, target_directory, checkpoint):
        remote_id = job.checkpoint.get("remote_id")
        if remote_id is None:
            remote_id = await self._client.submit(job.candidate.download_url)
            await checkpoint({"remote_id": remote_id})
        path = await self._client.wait(remote_id)
        await checkpoint({"remote_id": remote_id, "completed": True})
        return DownloadedAsset(path.directory, path.filename,
                               {"remote_id": remote_id, "completed": True})
```

`start_or_resume` 必须允许使用已有 checkpoint 重入，不能重复提交同一个远程任务。永久错误由 adapter 抛出明确异常；当前 worker 默认对每个步骤尝试三次。

Organizer 只负责移动、目录规划后的重命名及冲突处理。实现应在重试时识别目标已存在、源已消失的成功窗口，并返回实际最终路径。

扩展实现放在 `adapters/feed_sources`、`adapters/metadata_sources` 或 `adapters/download_backends`。`adapters/outbound` 已删除且不得重新创建；assistant 和内置 skills 也统一从 `adapters.configuration` 读取同一份应用配置。

## 提交检查

每个 adapter 至少提供以下合同测试：支持范围、正常结果、网络/权限错误、重复调用、关闭资源。涉及核心流程、配置、HTTP 或数据库结构的修改还必须更新 `docs/` 对应文档；CI 会检查这一约束。
