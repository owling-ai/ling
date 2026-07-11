# Docs Change log

## 2026-07-11

- 修复 ESP32 复用 `session_id` 重连后的 Gemini 上下文丢失：持久化业务会话、resumption handle 和文本历史，重连不再重复 opening。
- Gemini 上游连接失败改为设备 WebSocket 内退避重试，并补充 `response.cancel` 本地收尾、音频帧上限和泵任务清理。
- 加入孩子端先扫、家长端后扫同一二维码的黑客松绑定闭环，并区分 App Demo 绑定与生产账户、硬件鉴权。
- 重写根 README，以当前代码为准描述启动、四种实时 provider、媒体 worker、调试台与双 App 入口和生产边界。
- 新增文档索引与实现状态矩阵，明确产品规格是目标态，不等同于已交付。
- 将过时的 `Ling-实时音视频调研与决策记录-2026-07-10.md` 合并为 `docs/realtime.md`；移除费用、账号、旧提交号和已失效待办。
- 将 `Ling-ESP32客户端接入架构与接口方案.md` 合并为 `docs/esp32-device-api.md`；当前兼容协议与正式提案分开。
- 修正记忆架构中的 provider 类名和已实现范围：`MockMediaProvider`、`JimengArkProvider`，不再声称存在 Veo provider。
- 为产品总览、孩子端 App/家长端 App 规格、记忆架构和媒体生成页补充实现状态或 Change log。
- 世界线提示词保留为内容生产资料，不并入运行时技术文档。
- 将重复的孩子产品规格合并为孩子端 App「灵灵」：实体灵灵是硬件形态，“相处”是同一 App 内的状态；移除旧文件并同步索引、总览和实现状态。

## 维护约定

每次文档行为或边界变化至少记录日期、涉及页面和变化原因。纯错别字可不记。
