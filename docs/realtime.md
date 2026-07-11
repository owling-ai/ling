# 实时音视频接入

更新：2026-07-11。配置以 [`.env.example`](../.env.example) 为准。

## Provider 矩阵

| Provider | 传输 | 上行 | 下行 | 视频 | 主要限制 |
|---|---|---|---|---|---|
| Gemini 童声（浏览器） | ByteRTC + Gemini SSE | WebRTC 音视频 | `seed-tts-2.0` WebRTC 音频 | RTC 服务端抽帧送 Gemini | 级联延迟高于原生 Live；需公网 HTTPS 回调 |
| Gemini 童声（ESP32） | Ling PCM 网关 | 16 kHz PCM16，经独立流式 ASR | 24 kHz PCM16“小晴天” | 不支持 | 保留旧固件协议；需独立 Speech API Key |
| StepFun | Ling WebSocket 代理 | 24 kHz PCM16 | 24 kHz PCM16 | 不支持 | 纯语音通道 |
| MiniCPM-o | Ling WebSocket 代理 | 浏览器 16 kHz PCM16，后端转 float32 | 后端转回 24 kHz PCM16 | 最近 JPEG | 公开协议无用户 ASR；不支持后台冷场文本指令 |
| 火山 Ark RTC | ByteRTC | WebRTC 音视频 | WebRTC AI 音频 | RTC 服务端抽帧 | Gemini 回调未配置时的降级模式 |

API key 和 RTC 私钥只在后端。进入页面不会申请权限或连接；点击接通后才创建业务会话并建立实时链路。

## 选择规则

`LING_REALTIME_PROVIDER` 可显式指定 `gemini`、`stepfun`、`volcengine` 或 `minicpm`。未指定时：

1. 浏览器同时配置 Gemini API Key、火山四项 RTC 凭证和 `LING_VOLC_GEMINI_LLM_URL` 时，优先使用 ByteRTC Gemini 童声；
2. 现有 ESP32 另需 `VOLCENGINE_SPEECH_API_KEY` 与 `LING_GEMINI_PCM_CHILD_TTS=1`，其 `provider=gemini` 使用 PCM 童声网关；
3. 其他 provider 依次按 StepFun、火山 Ark RTC、MiniCPM-o 可用性选择，绝不回退到 Gemini Live 原声音频。

旧调试台只显示一个“Gemini”入口，浏览器内部使用 `volcengine` 传输。ESP32 的同名入口由服务端路由到独立 ASR、Gemini 文本和童声 TTS；原生 Gemini Live 音频不再公开或参与产品路由。

## 原生童声 profile

服务端只允许两档：

- `sunny`：小晴天；
- `sprout`：小青芽。

网页调试台把试听选择保存在 `localStorage`，并可在 `/api/gemini/prepare` 时发送公开 profile ID。RTC 客户端省略音色时采用 `LING_VOLC_VOICE_PROFILE`，默认 `sunny`。ESP32 PCM 网关不接受 profile 参数，也使用该服务端默认值。服务端把 profile 固定为 `seed-tts-2.0` voice 和持久语气上下文，通话中不能切换；非法网页 ID 同样回退到 `sunny`。

试听是浏览器实际订阅 ByteRTC 远端轨道后录回的 24 kHz、单声道、16-bit PCM WAV。`frontend/assets/voices/manifest.json` 记录生产链路、公开 profile、时长、SHA-256 和匿名评审门槛；`scripts/validate_voice_previews.py` 负责校验。

详见 [原生童声音色方案](./custom-voice.md)。

## Gemini SSE 回调

火山 `CustomLLM` 按 OpenAI-compatible SSE 协议请求：

```text
POST /integrations/volcengine/gemini
Authorization: Bearer <per-process callback token>
Content-Type: application/json
```

Ling 将允许的 OpenAI 字段转发到 Gemini compatibility endpoint，并原样流回 `data: ...` 与 `data: [DONE]`。关键边界：

- 回调 URL 必须是公网 HTTPS；
- Token 每次进程启动随机生成，不复用管理令牌；
- Gemini API Key 不会进入 RTC 配置；
- `custom`、`X-Biz-Trace-Info` 等火山业务数据不会转发到 Gemini；
- 服务重启会使旧回调 Token 和旧 RTC 任务失效。

## 会话契约

```text
POST /api/session/start
  -> session_id, opening, review_items

WS /api/realtime/ws?session_id=...&provider=gemini|stepfun|minicpm&video=0|1
  provider=gemini + PCM 网关配置 -> 独立 ASR、Gemini 文本、默认童声 PCM

POST /api/gemini/prepare
  <- session_id[, voice_profile=sunny|sprout]  # 硬件省略 profile，默认 sunny
  -> RTC token, room/user/bot IDs, voice_profile, voice_name
POST /api/gemini/start|observe|subtitle|stop

POST /api/session/end
  -> 同步冷路径结果和 moment 状态
```

旧 `/api/volcengine/*` 路径仅为兼容别名。当前 WebSocket 媒体放在 JSON + Base64 中，现有 ESP32 可将它作为 P0 兼容协议，但它仍不是正式设备协议。业务 session、转写、记忆包和运行状态会落 SQLite；重连可恢复文本历史，但设备仍需重新建立 WebSocket 和 ASR 流。ByteRTC 媒体不走该 WebSocket，其 RTC 任务仍只保存在进程内，重启后不能恢复。

## 交互规则

- 开场只做纯问候；真实模型输出到达后才写入转写。
- StepFun 和两条 Gemini 童声路径每场最多两次受控冷场回应。
- 浏览器 Gemini 通过 `UpdateVoiceChat` 将缓存画面与文本送入 Gemini；ESP32 PCM 网关当前仅处理音频和文本。
- MiniCPM 不启用自动冷场回应。
- 孩子明确拒绝英语时，热路径立即进入 retreat，本场停止学习编织。

## 已知限制

- Gemini 童声是 ASR、文本 Gemini、TTS 级联，不具备 Gemini Live 原生音频模型全部的语气理解。
- 2026-07-11 三次后台触发测试到完整回复字幕为 `2.2-3.7s`；一次无视频测试的首个非静音下行音频约 `2.58s`。两次假麦克风完整回路中，从 ASR 定稿到首段回复字幕为 `0.85-1.1s`；仍需扩大真实说话、首音频帧和弱网样本。
- ESP32 PCM 网关不具备 ByteRTC 的视频、AEC 和 RTC 服务端打断能力；它以火山 ASR 的 `600ms` 判停和设备本地打断为基线。
- 真实旧协议回环中，ASR 正确识别完整测试句，Gemini 返回文本后得到 `499,288` 字节有效 24 kHz PCM；从 ASR 判停事件到首个完整 TTS 音频帧约 `2.54s`。
- MiniCPM 当前没有用户侧转写，依赖用户文本的记忆和词汇记账不完整。
- StepFun 当前不发送视频。
- 火山必须使用“AI 音视频互动方案”应用，不能混用“实时对话式 AI”AppId。
- ESP32 不直接复用 ByteRTC Web SDK；当前通过后端 PCM 网关接入，量产仍应迁移到带设备鉴权和二进制媒体帧的正式协议。
- `websockets` 会读取系统代理变量；`wss://` 上游需要代理正确支持 CONNECT 与 WebSocket Upgrade。Gemini 可用 `LING_GEMINI_USE_PROXY=false` 强制直连。
- 独立 Speech SaaS 的流式 ASR 与 `seed-tts-2.0` 已开通；API Key 仅保存在后端 `.env`，浏览器、设备、公开 state 和 manifest 均不可获得。

## Change log

- `2026-07-11`：现有 ESP32 的 `provider=gemini` 改接独立流式 ASR、Gemini 标准文本模型和默认“小晴天”PCM；不调用 Gemini Live 原声音频。
- `2026-07-11`：移除四个 Gemini 成人角色音色；加入两档原生童声、Gemini SSE 回调、RTC profile 绑定和实际 RTC 试听。
- `2026-07-11`：从 2026-07-10 调研记录提取仍有效结论；加入 MiniCPM，删除账户、费用、提交号和排障过程等易过期内容。
- `2026-07-11`：补充 Gemini Live session resumption、SQLite 历史回放、上游退避重连和设备帧上限行为。
