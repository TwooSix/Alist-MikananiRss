# 数据迁移与兼容

## 自动迁移

默认数据库仍是 `data/data.db`。后端启动前自动执行迁移；也可以独立运行：

```bash
openlist-ani-migrate
```

Docker 同时启用 assistant 时，entrypoint 会先完成迁移，再启动两个进程，避免 assistant 打开旧数据库后 Windows/SQLite 无法原子切换。

迁移流程：

1. 通过 SQLite backup API 把旧 `data.db` 复制到 `data/backups/data-v1-<UTC时间>.db`。
2. 复制到同目录临时数据库并添加新 schema。
3. 从 `data/task_mementos.db` 导入任务；只有该文件不存在时才回退到 `task_mementos.json`。文件存在但损坏、缺表或无法解析时迁移失败，避免悄悄忽略更权威的数据源。
4. 保留任务 ID、OpenList downloader 类型、checkpoint、已下载文件位置、重试次数和时间字段。
5. 执行 `PRAGMA quick_check`，核对迁移前后资源数、发现的旧任务数，并逐个确认旧 task ID 存在于新数据库。任意 payload 无法转换都会使整个临时迁移回滚。
6. 关闭 SQLite 连接并清理已被 backup API 合并的旧 WAL/SHM sidecar，使用 `os.replace` 原子替换 `data/data.db`。

迁移成功后，旧 task memento 文件保持只读，不再写入。重复执行通过 `schema_migrations` 和唯一键跳过，不会重复导入。

## 兼容范围

- `resources` 的所有旧列、类型和 `title` 唯一语义保留。
- 新增列为 `job_id`、`final_path`、`metadata_json` 和 `provenance_json`。
- 当前 schema 版本为 v3；`jobs` 和 `notification_outbox` 新增内部 lease token/过期时间列，用于运行期自动回收中断任务，不属于公开兼容接口。
- `metadata_json`/`provenance_json` 中的新证据会携带 `value`、`previous_value` 和 `overrode`。旧 JSON 缺少这些键时按 `null`、`null`、`false` 读取，不需要数据库迁移或重写历史资源。
- assistant 继续直接查询同一个 `data/data.db/resources`。
- 现有 `/api/rss`、`/api/downloads`、`/api/parse_rss`、`/api/resolve_magnet` 和 `/api/resolve_torrent` 路径及响应字段保留。
- 新增 `/health/live` 和 `/health/ready`。
- 旧配置不会在启动时自动重写。
- `notification.batch_interval` 仍能被旧配置模型读取；新核心为保证 outbox 的持久化语义，实际逐条投递通知，不再把已领取行转交给内存批次后提前标记完成。

旧配置的编译规则：

```text
metadata_parser.provider + metadata_validator.provider
                         -> CoreSettings.metadata_providers
```

用户显式提供 `[metadata].providers` 时使用新列表。通过 API 添加 RSS 时，只原子更新 `rss.urls`，TOML 其他内容和注释保持不变，并立即唤醒 Scheduler。

## 回滚

1. 停止 backend 和 assistant，确保没有进程占用 `data/data.db`。
2. 复制当前 v3 数据库到安全位置，以免丢失迁移后新增资源。
3. 从 `data/backups/` 选择迁移前备份，替换 `data/data.db`。
4. 使用旧版本程序启动；旧 `task_mementos.db/json` 仍在原位置。

旧版本无法识别迁移后新完成的 durable jobs。需要完整回滚这些数据时，应先导出 `resources` 中迁移后的行再人工合并，不要直接在运行中的数据库上改 schema。

## 故障处理

- 临时数据库校验失败：原数据库不会被替换，可修正损坏的 task payload 后重试。
- 原子替换报“文件正在使用”：停止所有读取 `data.db` 的进程再运行迁移。
- 单条旧 task 无法反序列化：迁移整体失败且原数据库不切换；日志会给出 payload 下标和 task ID，修复旧文件副本后重试。
- `task_mementos.db` 存在但损坏或缺少预期表：不会回退 JSON；应先确认哪个文件才是最新真相，再修复或显式移走损坏的 DB 副本。
- 数据库已是当前版本：迁移命令不创建新备份，也不修改文件。
