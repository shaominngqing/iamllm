# Flutter 手机管理端

`mobile/` 是可运行的 Flutter iOS/Android 工程，定位是“随时接管真人模型”，不是把桌面控制台所有低频设置塞进手机。

已实现：

- 扫码配对、8 位一次性配对码和管理员备用登录；
- Keychain/Keystore 安全存储与自动 refresh token 轮换；
- 待回答、已回答、已过期队列；
- ChatGPT 风格的四栏移动工作台与手机窄屏布局；
- SSE 断线重连和 `Last-Event-ID` 续传；
- 用户可见聊天、运行摘要、懒加载原始上下文；
- 多个流式 chunk 自动合并为一条助手消息；
- 带鉴权的图片预览和文件卡片；
- 快捷回复、草稿保存、逐段 chunk、空白结束规则；
- 工具选择和 JSON 参数调用；
- 自动回复规则与快捷话术的创建、编辑、启停和删除；
- API 密钥申请、额度设置、一次性密钥展示和撤销；
- 服务状态、公开资料和管理设备详情；
- 幂等 `chunk_id` 与跨设备回答冲突提示。

## 运行

```bash
cd mobile
flutter pub get
flutter run
```

应用不内置服务器地址。网页生成的二维码使用
`iamllm://pair?server=<instance-url>&code=<one-time-code>`，手机扫码后校验协议、地址与 8 位配对码，再调用现有配对 API。

开发环境可使用 HTTP；Android 清单和 iOS Info.plist 已允许本地调试连接。正式发布必须填写 HTTPS 地址，并按自己的应用标识完成签名。

## 上架前仍由部署者配置

- Bundle ID / applicationId、应用名、图标和启动页；
- Apple Developer 与 Android keystore 签名；
- 若需要后台系统通知，配置自己的 APNs/FCM 网关，并让 `IAMLLM_NOTIFICATION_WEBHOOK_URL` 指向它；
- 隐私政策、崩溃收集开关和商店素材。

推送只负责唤醒和提示，不携带完整对话正文。应用被打开后仍通过 Admin API 拉取权威状态。
