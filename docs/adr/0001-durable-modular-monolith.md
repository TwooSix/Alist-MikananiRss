# ADR-0001：采用 SQLite 持久化任务的异步模块化单体

- 状态：已接受
- 日期：2026-08-02

## 背景

原核心通过通用 PipelineStage、多级内存队列、事件管理器和独立 task memento 写路径协调 RSS、解析、下载、重命名与通知。进程中断后需要跨 `data.db`、task SQLite/JSON 和内存队列推断真实状态，重复 Registry 也让新增 adapter 需要修改多处。

## 决策

使用单进程 asyncio 模块化单体，SQLite `jobs` 是任务状态唯一真相来源。worker 通过短事务领取、带 fencing token 的可过期 lease、checkpoint、重试和完成任务；通知使用同库 outbox。远程提交和文件移动先持久化意图状态，恢复时先查询外部事实再决定是否重做。保留显式的 domain、application、adapters、bootstrap 依赖方向和唯一启动注册中心。

不引入 Redis、Celery、微服务、运行时第三方插件系统或重量级依赖注入框架。

## 结果

- 进程重启可从明确步骤恢复，不依赖内存队列。
- 单个 worker 在进程仍存活时异常退出，过期任务也能自动被其他 worker 回收；旧 worker 的迟到写入会被 lease token 拒绝。
- 下载完成与资源入库、通知创建可原子提交。
- 单个 RSS 或外部服务故障可以独立退避。
- 扩展需要实现窄协议并显式注册，部署仍是一个进程和一个数据库。
- SQLite 写入由单连接短事务串行化；这是当前规模下换取一致性和低运维成本的有意选择。若未来测得持续写入成为瓶颈，再以指标和 ADR 决定是否拆分。
