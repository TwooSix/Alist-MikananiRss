# 开发与测试

## 本地命令

```bash
uv sync --all-groups
uv run ruff check .
uv run black --check .
uv run pytest -q
uv build
```

`ripgrep` 是开发者或容器中的系统工具，不再是 Python 核心依赖。Docker 镜像仍通过系统包安装它，因此 Windows 不会因缺少 MSVC linker 而无法建立测试环境。

## 测试分层

- `tests/domain`：元数据覆盖、状态转换和命名纯规则。
- `tests/application`：Scheduler、worker、过滤和应用服务。
- `tests/adapters`：RSS、元数据、下载、配置和 SQLite 合同。
- `tests/compatibility`：旧配置、资源库、memento 和 HTTP/SQL 兼容。
- `tests/resilience`：进程中断、远程副作用窗口、并发和资源关闭。
- `tests/assistant`：assistant 原有回归，核心重构不得改变其业务行为。

网络 adapter 测试不访问真实服务；使用 fake server/client 覆盖超时、429/5xx、权限错误、304 和无效数据。SQLite 测试使用真实临时文件，不 mock 事务。

元数据合并测试必须覆盖未知占位符不能覆盖有效值、同级/跨级覆盖顺序、每一步的 `value`/`previous_value`/`overrode`，以及读取缺少这些新证据字段的旧 JSON。RSS adapter 没有解析出的字段应使用 `None` 或空列表，不能用 `unknown` 声明自己拥有更高优先级的数据。

## 崩溃恢复测试点

下载工作流至少覆盖以下中断位置：

1. 远程任务提交前后。
2. 下载完成 checkpoint 前后。
3. 临时文件移动到媒体目录前后。
4. 目标文件名持久化后、远程重命名前后。
5. `resources + completed job + outbox` 事务提交前后。
6. 通知发送前后。

测试方式是留下 `running`/`sending` 行、让 lease 过期，或只完成远程 fake 副作用，然后重新创建 repository/worker。断言失去 lease 的旧 worker 不能再落库，远程任务不重复提交，文件不重复移动，最终只能有一个 job、一个资源行和一个 outbox 行。迁移测试还必须包含损坏 payload、损坏 task DB 和重复执行，任何无法转换的旧任务都应阻止原子切换。

## 真实崩溃恢复 E2E

在隔离副本上运行真实 RSS、元数据服务、OpenList 下载和通知链路：

```bash
uv run python tests/manual_test_script/e2e_crash_recovery.py \
  --config config.toml \
  --database data/data.db \
  --tool qBittorrent \
  --stage-timeout 14400 \
  --final-timeout 14400
```

脚本只复制并修改临时配置和数据库，不改写传入的原文件。它解析 RSS 中与旧资源库标题完全匹配的 torrent 元数据，默认选择体积最小的候选；`--target-contains` 可进一步缩小范围。脚本为测试创建唯一远程目录，对同一个 job 依次在 RSS 返回后、metadata provider 前、远程提交后、各下载 checkpoint、移动后、重命名后、最终事务前和通知发送前强制终止整个子进程树。每次都用同一数据库重启，最后核对任务完成、资源与来源证据入库、outbox 已投递、只有一个离线任务和一个最终文件、文件大小等于 torrent 元数据、临时任务目录不存在。运行前后还会校验原配置/数据库哈希；包含真实凭据的本地临时目录和子进程必须清零，远程结果保留供人工复核。

指定的下载工具必须已经在 OpenList 服务端启用。健康检查失败时脚本会在 RSS、下载和通知副作用前退出，例如服务端未配置 `qBittorrent` 时不能仅靠修改本地 `offline_download_tool` 完成测试。最终恢复会实际发送一次下载完成通知，运行前应确认所用配置允许该操作。

## 代码约束

- application 不得导入 adapters；具体实现只在 bootstrap 组合。
- 不新增无界队列、进程级隐式 session、导入时读写配置或数据库。
- 数据库事务内不执行网络请求或长时间文件操作。
- provider batch、worker 数和缓存必须有硬上限。
- 新增外部系统只实现现有窄协议；不要再创建该类型专用 Registry。
- 不得重新创建或导入 `adapters.outbound`；运行时不得导入 migration 的私有 legacy 类型。
- 修改 `domain/application` 核心、配置、HTTP schema、持久化 schema 或 migration 时同步修改 `docs/`。

## 发布前验证

除全量测试外，至少用一份旧 `data.db` 与 task memento 副本运行 `openlist-ani-migrate`，核对备份、资源计数和 active jobs。随后在 OpenList 暂不可用、空 RSS、TMDB 暂不可用三种情况下启动，确认 `/health/ready` 报 degraded 且进程继续运行。
