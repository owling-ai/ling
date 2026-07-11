# Docs Change log

## 2026-07-11

- 重写根 README，以当前代码为准描述启动、四种实时 provider、媒体 worker、三端入口和生产边界。
- 新增文档索引与实现状态矩阵，明确产品规格是目标态，不等同于已交付。
- 将过时的 `Ling-实时音视频调研与决策记录-2026-07-10.md` 合并为 `docs/realtime.md`；移除费用、账号、旧提交号和已失效待办。
- 将 `Ling-ESP32客户端接入架构与接口方案.md` 合并为 `docs/esp32-device-api.md`；当前兼容协议与正式提案分开。
- 修正记忆架构中的 provider 类名和已实现范围：`MockMediaProvider`、`JimengArkProvider`，不再声称存在 Veo provider。
- 为产品总览、三端规格、记忆架构和媒体生成页补充实现状态或 Change log。
- 世界线提示词保留为内容生产资料，不并入运行时技术文档。

## 维护约定

每次文档行为或边界变化至少记录日期、涉及页面和变化原因。纯错别字可不记。
