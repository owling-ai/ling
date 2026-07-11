# Ling 实现状态

基线：2026-07-11 当前主工作树。事实来源为 `backend/`、`frontend/`、`tests/`、`.env.example` 与 `run.sh`。

## 已实现

- 一个 FastAPI 服务提供旧玩偶调试台、儿童 PWA、家长 PWA 与 JSON API。
- Gemini Live、StepFun、MiniCPM-o 经 `/api/realtime/ws` 代理；火山引擎使用 ByteRTC 与独立控制面 API。
- L1-L4、会话转写、事实演化、SRS、议程、私有 Canon、故事弧与成长快照落 SQLite。
- 会话结束幂等处理冷路径，并可创建最多两次 attempt 的专属瞬间生成任务。
- 基础世界由 `base_world.json` 驱动；视频变体分配持久化到 `world_assignments`。
- 儿童端实现世界当前态、公共/专属 feed、瞬间轮询、信物收藏与离线壳。
- 家长端实现今日、成长、分页记忆、守护四个只读投影。
- 媒体默认走可恢复 Mock 状态机；Seedance 任务可后台提交、轮询、下载并原子发布。
- 调试、会话、实时和 admin API 可通过本机检查或 `LING_ADMIN_TOKEN` 保护。

## 规格差异

| 规格主题 | 当前代码 | 结论 |
|---|---|---|
| 实体玩偶 | 只有浏览器模拟器 | 硬件未实现 |
| 首次孵化 | 旧调试台 onboarding；家长 PWA 欢迎页是本地展示 | 未形成正式跨端绑定流程 |
| 儿童端“去找灵灵” | 当前页提供体验入口，但实体设备跳转契约未冻结 | 部分实现 |
| 家长守护设置 | 时段、上限、提醒和 AI 身份由后端固定返回 | 只读展示，不可配置 |
| 红线管理 | onboarding 可写；家长 PWA 只读 | 管理流程未实现 |
| 数据导出/注销 | 只展示说明，响应明确标记不可用 | 未实现 |
| 多孩/多家庭 | 全局固定 `CHILD_ID=1` | 未实现 |
| 正式认证 | 仅 Demo 管理令牌；儿童/家长投影无账户身份 | 未实现 |
| 设备协议 | 没有 `/api/device/v1/*` | 仅有提案 |
| 多实例 | 会话锁与媒体 worker 以单进程为主，SQLite 持久化 | 不支持生产多实例 |
| 通知 | 只有投影文案 | 未投递 |
| 视觉动作主动门控 | Gemini/StepFun/火山支持有限冷场触发；MiniCPM 不支持后台文本触发 | 独立动作门控未实现 |
| 议程消费 | 会话开始即标记 `consumed` | 与“真实使用后消费”目标不一致 |

## 文档修正依据

- `/api/session/start` 当前只返回 `session_id`、`opening`、`review_items`，不再返回完整 `memory_pack`。
- `/api/session/end` 当前同步等待冷路径完成；不是正式设备协议期望的 `202 Accepted`。
- 现有 WebSocket 使用 JSON + Base64；MiniCPM 已加入，火山 RTC 不走该 WebSocket。
- 当前媒体类名是 `MockMediaProvider` 与 `JimengArkProvider`；代码中没有 `VeoVideoProvider`。
- 家长端产品名已统一为“成长手册”；旧调试台仍是开发工具，不是家长产品端。

## Change log

- `2026-07-11`：首次按代码建立实现矩阵；记录产品规格、硬件提案与当前 Demo 的边界。
