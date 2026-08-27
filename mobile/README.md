# iamllm Mobile

Flutter 管理端，一套代码运行于 iOS 和 Android。它只通过 iamllm 的 `/admin/api/v1` REST + SSE 契约工作，不直接连接服务端数据库。

移动端包含四个工作区：

- 会话：搜索与筛选请求、查看用户可见对话、合并展示流式 chunk、回复或调用工具；
- 自动回复：新建、编辑、启停和删除关键词/时间规则及快捷话术；
- API 密钥：申请独立密钥、设置额度、一次性查看并随时撤销；
- 服务：查看运行状态、编辑公开资料、检查和撤销管理设备。

```bash
flutter pub get
flutter analyze
flutter test
flutter run
```

首次连接默认使用扫码：网页控制台在「服务与设备」中生成二维码，二维码携带当前部署实例的地址和 8 位一次性配对码。应用不会内置任何服务器地址。

相机不可用时，仍可手工输入服务器地址与配对码；管理员账号密码仅作为部署者备用入口。正式分发建议使用 HTTPS。

详细功能、配对和发布准备见 [`../docs/flutter-mobile.md`](../docs/flutter-mobile.md)。
