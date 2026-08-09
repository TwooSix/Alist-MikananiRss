# ADR-0002：核心目录与模型彻底收口

- 状态：已接受
- 日期：2026-08-02

## 背景

SQLite durable runtime 落地后，核心仍处于“新 worker 包装旧 parser/downloader/domain”的过渡状态，同时存在 `AnimeRelease`、`DownloadJob`、`TaskMemento`、`PipelineContext` 和多套 adapter 目录。虽然运行流程已经持久化，这些重复类型仍增加跳转、转换和误用风险。

## 决策

核心只保留 `domain → application → adapters → bootstrap` 四层，以及 `ReleaseCandidate + MetadataDocument + DownloadJob` 一套运行时模型。RSS、regex、LLM、TMDB、OpenList、通知、torrent 和 HTTP 实现全部进入各自最终 adapter 目录。删除旧 ingestion Pipeline、parser/validator facade、任务 memento 在线模型、内存通知批次和专用 Registry。

`assistant`、内置 skills 和 messaging 的业务逻辑不参与本轮重构，但其配置导入统一切换到正式的 `adapters.configuration` 边界。`adapters/outbound` 整体删除，不保留旧 Python import 路径。旧 memento 读取能力只存在于 migration 私有 decoder，不得被运行时导入。

## 结果

- 新 RSS、metadata provider 或下载后端只需增加一个模块/小目录并在唯一 `AdapterRegistry` 显式注册。
- 下载 checkpoint 和 organizer 直接使用 `DownloadJob`，不再发生领域对象来回转换。
- 架构测试禁止旧目录（包括整个 `adapters/outbound`）、旧 import 路径、额外核心 Registry、application 反向依赖 adapters、domain 非标准库依赖和 legacy migration 类型泄漏。
- HTTP、配置版本、数据库路径及 assistant 查询保持兼容；通知在 durable outbox 上恢复 `batch_interval` 的有界聚合语义。
