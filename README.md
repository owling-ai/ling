# 灵 Ling · 共同成长的玩偶

儿童与家庭场景中的实体 agent Demo。实时对话、五层记忆、教材编织、基础世界、孩子端 App 与家长端 App 共用一套后端事实源。

## 快速开始

```bash
cp .env.example .env   # 按需配置实时模型；冷路径和媒体均有本地 Mock
./run.sh
```

默认监听 `0.0.0.0:8888`：

- `http://localhost:8888/`：玩偶模拟器与调试控制台。
- `http://localhost:8888/child/`：孩子端 App「灵灵」，当前实现 `现在 / 奇遇 / 口袋` 浏览状态。
- `http://localhost:8888/parent/`：家长端 App「成长手册」。

首次启动自动创建 SQLite 数据库并预埋 Demo 数据。没有冷路径 API key 时使用规则抽取器；没有媒体 API key 时使用本地 `MockMediaProvider`。实时通话仍需至少配置一个实时 provider。

> `run.sh` 为联调方便，默认设置 `LING_ALLOW_UNAUTHENTICATED=1`。不要直接用于公网。需要保护调试、会话和实时接口时，设置 `LING_ALLOW_UNAUTHENTICATED=0` 与 `LING_ADMIN_TOKEN`；只需本机访问时同时设置 `LING_HOST=127.0.0.1`。

## 当前能力

| 模块 | 已实现 | 当前边界 |
|---|---|---|
| 实时交互 | Gemini 童声 RTC、StepFun、MiniCPM-o、火山 Ark RTC | 浏览器联调协议；不是正式设备协议 |
| 记忆 | L1-L4 持久化、L0 会话态、事实演化、SRS、私有 Canon | 单孩子 `CHILD_ID=1`；SQLite 单实例 |
| 孩子端 App「灵灵」 | `现在 / 奇遇 / 口袋` PWA | 投影读取与口袋收藏已实现；“相处”模式尚未整合 |
| 家长端 App「成长手册」 | `今日 / 成长 / 记忆 / 守护` PWA | 当前为只读投影；守护设置不写回 |
| 双端绑定 Demo | 孩子端先扫、家长端后扫同一登记二维码 | 固定单孩、单玩偶；不是生产账户系统 |
| 媒体 | 本地 Mock 状态机、可恢复 Seedance 2.0 任务 | 真实生成用于离线准备，不作为现场依赖 |
| 数据权利 | 产品语义与只读说明 | 导出、注销和完整级联销毁未实现 |
| 硬件 | 可复用现有会话与 WebSocket 做 P0 原型 | 设备身份、绑定、二进制协议、重连均未实现 |

更完整的代码与文档差异见 [实现状态](./docs/implementation-status.md)。

## 双端绑定演示

打开根页面的“演示控制台”，电脑会显示 Demo 二维码。使用两台手机按顺序操作：

1. 孩子端打开 `/child/`，扫描二维码后等待家长；
2. 家长端打开 `/parent/`，扫描同一二维码，双方立即完成绑定；
3. 需要重演时，在演示控制台点击“重置绑定”，再打开两个重置链接。

相机扫码同时支持浏览器原生 `BarcodeDetector` 与本地 `jsQR`；最后可手动输入默认码 `LING-DEMO-2026`。默认码可通过 `LING_DEMO_BINDING_CODE` 覆盖。

## 实时模型

任配一种。完整变量见 [`.env.example`](./.env.example)，协议差异见 [实时音视频接入](./docs/realtime.md)。

```bash
# Gemini 原生童声链路：Gemini 文本模型 + ByteRTC ASR/TTS/打断/视频
GEMINI_API_KEY=...
VOLCENGINE_RTC_APP_ID=...
VOLCENGINE_RTC_APP_KEY=...
VOLCENGINE_ACCESS_KEY=...
VOLCENGINE_SECRET_KEY=...
LING_VOLC_GEMINI_LLM_URL=https://ling.example.com/integrations/volcengine/gemini
LING_VOLC_GEMINI_MODEL=gemini-3.1-flash-lite
LING_VOLC_VOICE_PROFILE=sunny  # sunny（小晴天）| sprout（小青芽）

# 其他可选 provider
STEPFUN_API_KEY=...
LING_MINICPM_BASE_URL=http://192.168.1.9:9000/v1
```

`LING_VOLC_GEMINI_LLM_URL` 必须是公网可访问的 HTTPS 地址，并指向当前服务的固定回调路径。回调使用每次进程启动时生成的独立 Bearer Token，Gemini API Key 不会发给火山引擎。配好该 URL 后默认选择 `volcengine` 传输，但 LLM 仍是 Gemini；未配置时 Gemini 不可用，可降级到火山 Ark、StepFun 或 MiniCPM-o，绝不回退到 Gemini Live 原声音频。

旧调试台只显示一个“Gemini”入口，并在其中提供“小晴天 / 小青芽”两档可试听童声；RTC 客户端不传音色时由后端直接使用默认“小晴天”。两档均来自火山官方公版 `seed-tts-2.0` 白名单，不使用真人儿童录音、声音复制或 DSP 升调。完整验证和边界见 [定制音色方案](./docs/custom-voice.md)。

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
浏览器玩偶 -> 会话服务 -> StepFun / MiniCPM-o
                        -> ByteRTC ASR + 打断 + 视频
                              -> Gemini SSE 文本模型
                              -> seed-tts-2.0 原生童声
      | 双向转写
      v
热路径：记忆包预取、转写记账、撤退规则、Canon
      | 会话结束
      v
冷路径：日记、事实、掌握度、反思、专属瞬间
      |
      +-> 孩子端 App 受控投影
      `-> 家长端 App 受控投影
```

```text
backend/
  app.py             FastAPI 路由、鉴权边界、静态应用
  db.py              SQLite schema 与迁移
  engine.py          会话生命周期与热路径记账
  memory.py          L1-L4 与记忆包
  life.py            议程、SRS、基础世界、私有故事
  workers.py         会后冷路径
  bindings.py        孩子端与家长端扫码绑定状态机
  realtime.py        实时 provider 路由、StepFun / MiniCPM 代理
  voice_profiles.py  原生童声白名单、默认值与公开字段
  volcengine_rtc.py  ByteRTC 控制面、Gemini SSE 适配与字幕
  experience.py      孩子/家长投影、瞬间与信物
  media.py           Manifest 与 Mock provider
  jimeng_video.py    Seedance provider
  media_worker.py    可恢复媒体任务 worker
frontend/
  index.html          玩偶模拟器与调试台
  assets/voices/      实际 ByteRTC 录回的童声试听 WAV 与 manifest
  child/              孩子端 App PWA
  parent/             家长端 App PWA
scripts/
  validate_voice_previews.py  校验试听格式、哈希、削波与评审门槛
```

## 验证

```bash
uv run python -m pytest -q
node --test frontend/child/tests/*.test.mjs
node --test frontend/parent/tests/*.test.mjs
uv run python -m compileall -q backend tests
uv run python scripts/validate_voice_previews.py
```

## 文档

从 [文档索引](./docs/README.md) 进入。产品规格描述目标体验；README、实现状态和专题技术文档描述当前代码。文档整理记录见 [Docs Change log](./docs/CHANGELOG.md)。

## Change log

- `2026-07-11`：移除四个成人底色的 Gemini 角色音色；加入“小晴天 / 小青芽”两档原生童声、Gemini SSE 适配和真实 ByteRTC 试听。
- `2026-07-11`：加入孩子端先扫、家长端后扫同一二维码的黑客松绑定闭环与现场重置入口。
- `2026-07-11`：将面向孩子的产品统一称为孩子端 App「灵灵」；根页面仍明确标为玩偶模拟器与调试控制台。
- `2026-07-11`：按当前代码重写启动、能力边界、provider、目录和文档入口；移除已过时的长篇调研内容。
