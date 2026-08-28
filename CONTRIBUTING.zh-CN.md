# 贡献指南

[English](CONTRIBUTING.md) · [简体中文](CONTRIBUTING.zh-CN.md)

感谢你愿意让 iamllm 更好用。这个项目优先追求“一个人能看懂、能部署、能长期维护”，功能数量不是唯一目标。

## 开始之前

- Bug 请附最小复现、客户端名称与版本、使用的协议端点、预期结果和实际结果；
- 产品建议请先说明使用场景和目标用户，不必一开始就指定技术方案；
- 不要在 Issue、日志或截图中提交真实 API Key、管理员凭据、会话原文和私有文件路径；
- 大型架构调整建议先开 Issue 对齐边界，避免实现完成后才发现方向不同。

## 本地环境

需要 Go 1.25、Node.js 22 和 Flutter stable：

```bash
cp .env.example .env
set -a; source .env; set +a
make dev
```

运行全量检查：

```bash
make test
docker build -t iamllm:test .
```

只修改 Web 时至少运行 `make web`；只修改 Flutter 时至少运行 `flutter analyze` 和 `flutter test`。

## 架构边界

- `internal/protocol` 只负责厂商请求/响应与领域对象之间的转换；
- 队列、等待、自动回复、额度和设备会话属于 `internal/application`；
- 业务代码依赖 `internal/repository` 接口，不直接依赖 SQLite 细节；
- React 和 Flutter 共用版本化 Admin API，不直连数据库；
- 新客户端应优先复用现有协议，只有无法表达的能力才新增兼容层；
- 当前产品是单实例，不要用不完整的分布式抽象增加部署成本。

更完整的说明见 [架构文档](docs/zh-CN/architecture.md)。

## 提交要求

一个易于审查的 Pull Request 应包含：

1. 清楚说明改变了什么、为什么；
2. 保持改动聚焦，不顺手重写无关模块；
3. 为错误修复补充能先失败、修复后通过的测试；
4. 修改公开 API、环境变量或 UI 流程时同步更新文档；
5. 不提交构建产物、真实 `.env`、数据库、签名文件或个人配置；
6. 确认 `make test` 和 `docker build` 通过。

提交信息建议使用简短的英文类型前缀，例如：

```text
feat: add scheduled auto reply
fix: merge streamed chunks in conversation view
docs: document Claude Code setup
```

## 数据结构变更

项目当前只保留一份干净的基线 schema。第一个稳定版本发布后，已发布 schema 的变更必须使用向前迁移，不能要求用户删除数据库。

修改仓储实现时，应覆盖创建、读取、并发冲突、幂等和重启后恢复等关键行为。

## UI 与交互

- 网页优先保证桌面管理效率和清楚的信息层级；
- Flutter 遵循 iOS 风格的间距、圆角、导航和反馈，同时保持 Android 可用；
- 多个流式 chunk 在聊天语义上是一条助手消息；技术细节进入“运行记录”；
- 用户可见聊天、内部上下文和工具执行必须有明确边界；
- 加载、空状态、错误、重试和断线恢复都属于功能的一部分。

## License

提交代码即表示你同意贡献内容按项目的 [MIT License](LICENSE) 发布。
