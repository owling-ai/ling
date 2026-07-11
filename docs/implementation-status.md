# Ling 实现状态

基线：2026-07-11 当前主工作树。事实来源为 `backend/`、`frontend/`、`tests/`、`.env.example` 与 `run.sh`。

## 已实现

- 一个 FastAPI 服务提供旧玩偶调试台、孩子端 App PWA、家长端 App PWA 与 JSON API。调试台不是独立产品端。
- Gemini Live、StepFun、MiniCPM-o 经 `/api/realtime/ws` 代理；火山引擎使用 ByteRTC 与独立控制面 API。
- L1-L4、会话转写、事实演化、SRS、议程、私有 Canon、故事弧与成长快照落 SQLite。
- 会话结束幂等处理冷路径，并可创建最多两次 attempt 的专属瞬间生成任务。
- 基础世界由 `base_world.json` 驱动；视频变体分配持久化到 `world_assignments`。
- 孩子端 App 实现世界当前态、公共/专属 feed、瞬间轮询、信物收藏与离线壳；“相处”模式尚未整合。
- 家长端 App 实现今日、成长、分页记忆、守护四个只读投影。
- 双端绑定 Demo 已实现：孩子端先扫登记二维码进入等待，家长端后扫同一码后激活；状态落 SQLite，可从演示控制台重置。
- 媒体默认走可恢复 Mock 状态机；Seedance 任务可后台提交、轮询、下载并原子发布。
- 调试、会话、实时和 admin API 可通过本机检查或 `LING_ADMIN_TOKEN` 保护。
- Gemini 实时会话支持 SQLite session 恢复、官方 resumption token、文本历史兜底、上游退避重连和下行音频帧分片；设备正式二进制协议仍未实现。

## 规格差异

| 规格主题 | 当前代码 | 结论 |
|---|---|---|
| 实体玩偶 | 只有浏览器模拟器 | 硬件未实现 |
| 首次孵化 | 两个 PWA 已形成孩子先扫、家长后扫的 Demo 绑定流程 | 固定 `CHILD_ID=1`，不是正式账户/家庭系统 |
| 孩子端 App“相处”模式 | 当前页只有“去找灵灵”体验入口；实时交互仍在根页面调试台，实体设备跳转契约未冻结 | 部分实现 |
| 家长守护设置 | 时段、上限、提醒和 AI 身份由后端固定返回 | 只读展示，不可配置 |
| 红线管理 | onboarding 可写；家长 PWA 只读 | 管理流程未实现 |
| 数据导出/注销 | 只展示说明，响应明确标记不可用 | 未实现 |
| 多孩/多家庭 | 全局固定 `CHILD_ID=1` | 未实现 |
| 正式认证 | 绑定以两端 installation ID 区分客户端；投影仍无账户身份 | 生产认证未实现 |
| 设备协议 | App 二维码绑定已实现；没有 `/api/device/v1/*` 或硬件身份证明 | 设备协议仍仅有提案 |
| 多实例 | 会话锁与媒体 worker 以单进程为主，SQLite 持久化；实时恢复依赖单实例连接状态 | 不支持生产多实例 |
| 通知 | 只有投影文案 | 未投递 |
| 视觉动作主动门控 | Gemini/StepFun/火山支持有限冷场触发；MiniCPM 不支持后台文本触发 | 独立动作门控未实现 |
| 议程消费 | 会话开始即标记 `consumed` | 与“真实使用后消费”目标不一致 |

## 文档修正依据

- `/api/session/start` 当前只返回 `session_id`、`opening`、`review_items`，不再返回完整 `memory_pack`。
- `/api/session/end` 当前同步等待冷路径完成；不是正式设备协议期望的 `202 Accepted`。
- 现有 WebSocket 使用 JSON + Base64；MiniCPM 已加入，火山 RTC 不走该 WebSocket。
- 当前媒体类名是 `MockMediaProvider` 与 `JimengArkProvider`；代码中没有 `VeoVideoProvider`。
- 面向孩子的产品统一为孩子端 App「灵灵」；当前 `child/` 只实现浏览状态，旧调试台仍是开发工具，不是额外的孩子产品端。

## Change log

- `2026-07-11`：记录黑客松双端扫码绑定已经落地，并明确它不等同于生产账户或硬件鉴权。
- `2026-07-11`：明确孩子端 App「灵灵」是唯一孩子 App；根页面仅为实体玩偶模拟器与调试工具。
- `2026-07-11`：首次按代码建立实现矩阵；记录产品规格、硬件提案与当前 Demo 的边界。
