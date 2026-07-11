# 灵 Ling · 共同成长的玩偶

儿童与家庭场景中的实体 agent Demo。实时对话、五层记忆、教材编织、基础世界、儿童端与家长端共用一套后端事实源。

## 快速开始

```bash
cp .env.example .env   # 按需配置实时模型；冷路径和媒体均有本地 Mock
./run.sh
```

默认监听 `0.0.0.0:8888`：

- `http://localhost:8888/`：玩偶模拟器与调试控制台。
- `http://localhost:8888/child/`：儿童端「灵灵的窗口」。
- `http://localhost:8888/parent/`：家长端「成长手册」。

首次启动自动创建 SQLite 数据库并预埋 Demo 数据。没有冷路径 API key 时使用规则抽取器；没有媒体 API key 时使用本地 `MockMediaProvider`。实时通话仍需至少配置一个实时 provider。

> `run.sh` 为联调方便，默认设置 `LING_ALLOW_UNAUTHENTICATED=1`。不要直接用于公网。需要保护调试、会话和实时接口时，设置 `LING_ALLOW_UNAUTHENTICATED=0` 与 `LING_ADMIN_TOKEN`；只需本机访问时同时设置 `LING_HOST=127.0.0.1`。

## 当前能力

| 模块 | 已实现 | 当前边界 |
|---|---|---|
| 实时交互 | Gemini Live、StepFun、MiniCPM-o、火山 RTC | 浏览器联调协议；不是正式设备协议 |
| 记忆 | L1-L4 持久化、L0 会话态、事实演化、SRS、私有 Canon | 单孩子 `CHILD_ID=1`；SQLite 单实例 |
| 儿童端 | `现在 / 奇遇 / 口袋` PWA | 投影读取与口袋收藏已实现 |
| 家长端 | `今日 / 成长 / 记忆 / 守护` PWA | 当前为只读投影；守护设置不写回 |
| 媒体 | 本地 Mock 状态机、可恢复 Seedance 2.0 任务 | 真实生成用于离线准备，不作为现场依赖 |
| 数据权利 | 产品语义与只读说明 | 导出、注销和完整级联销毁未实现 |
| 硬件 | 可复用现有会话与 WebSocket 做 P0 原型 | 设备身份、绑定、二进制协议、重连均未实现 |

更完整的代码与文档差异见 [实现状态](./docs/implementation-status.md)。

## 实时模型

任配一种。完整变量见 [`.env.example`](./.env.example)，协议差异见 [实时音视频接入](./docs/realtime.md)。

```bash
# Gemini Live
GEMINI_API_KEY=...

# StepFun
STEPFUN_API_KEY=...

# 局域网 MiniCPM-o
LING_MINICPM_BASE_URL=http://192.168.1.9:9000/v1

# 火山 RTC 需要 AppId、AppKey、IAM AK/SK 四项凭证
VOLCENGINE_RTC_APP_ID=...
VOLCENGINE_RTC_APP_KEY=...
VOLCENGINE_ACCESS_KEY=...
VOLCENGINE_SECRET_KEY=...
```

可用 provider 会显示在旧调试台中。`LING_REALTIME_PROVIDER` 可指定默认值：`gemini`、`stepfun`、`minicpm` 或 `volcengine`。

## 冷路径与媒体

记忆工人按 OpenAI 兼容端点、Anthropic、本地规则抽取器依次降级：

```bash
LING_WORKER_BASE_URL=https://api.example.com/v1
LING_WORKER_API_KEY=...
LING_WORKER_MODEL=deepseek-chat
```

媒体默认使用 Mock。真实 Seedance 任务的配置、轮询和持久化契约见 [视频生成链路](./docs/media-generation.md)。现场演示建议固定：

```bash
LING_MEDIA_PROVIDER=mock ./run.sh
```

触发专属瞬间：

```bash
curl -X POST http://localhost:8888/api/admin/demo-moment \
  -H 'Content-Type: application/json' \
  -d '{"event_key":"canon_choice","event_value":"橡果味","source_id":"demo-1"}'
```

## 架构

```text
浏览器玩偶 -> 会话服务 -> Gemini / StepFun / MiniCPM-o
                        -> 火山 RTC 控制面（媒体走 ByteRTC）
      | 双向转写
      v
热路径：记忆包预取、转写记账、撤退规则、Canon
      | 会话结束
      v
冷路径：日记、事实、掌握度、反思、专属瞬间
      |
      +-> 儿童端受控投影
      `-> 家长端受控投影
```

```text
backend/
  app.py             FastAPI 路由、鉴权边界、静态应用
  db.py              SQLite schema 与迁移
  engine.py          会话生命周期与热路径记账
  memory.py          L1-L4 与记忆包
  life.py            议程、SRS、基础世界、私有故事
  workers.py         会后冷路径
  realtime.py        Gemini / StepFun / MiniCPM 实时代理
  volcengine_rtc.py  火山 RTC 控制面与字幕
  experience.py      儿童/家长投影、瞬间与信物
  media.py           Manifest 与 Mock provider
  jimeng_video.py    Seedance provider
  media_worker.py    可恢复媒体任务 worker
frontend/
  index.html          玩偶模拟器与调试台
  child/              儿童 PWA
  parent/             家长 PWA
```

## 验证

```bash
uv run python -m pytest -q
node --test frontend/child/tests/*.test.mjs
node --test frontend/parent/tests/*.test.mjs
uv run python -m compileall -q backend tests
```

## 文档

从 [文档索引](./docs/README.md) 进入。产品规格描述目标体验；README、实现状态和专题技术文档描述当前代码。文档整理记录见 [Docs Change log](./docs/CHANGELOG.md)。

## Change log

- `2026-07-11`：按当前代码重写启动、能力边界、provider、目录和文档入口；移除已过时的长篇调研内容。
