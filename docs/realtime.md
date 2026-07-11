# 实时音视频接入

更新：2026-07-11。配置以 [`.env.example`](../.env.example) 为准。

## Provider 矩阵

| Provider | 传输 | 上行 | 下行 | 视频 | 主要限制 |
|---|---|---|---|---|---|
| Gemini Live | Ling WebSocket 代理 | 16 kHz PCM16 | 24 kHz PCM16 | JPEG，最长边 512px，约 1 FPS | 集成转写可能与实际声音不完全一致 |
| StepFun | Ling WebSocket 代理 | 24 kHz PCM16 | 24 kHz PCM16 | 不支持 | 纯语音通道 |
| MiniCPM-o | Ling WebSocket 代理 | 浏览器 16 kHz PCM16，后端转 float32 | 后端转回 24 kHz PCM16 | 支持最近 JPEG | 公开协议无用户 ASR；不支持后台冷场文本指令 |
| 火山 RTC | 浏览器 ByteRTC | WebRTC 音视频 | WebRTC AI 音频 | 服务端抽帧 | 需要四项凭证；不走 `/api/realtime/ws` 媒体面 |

API key 和 RTC 私钥只在后端。进入页面不会申请权限或连接；点击接通后才创建业务会话并建立实时链路。

## 选择规则

`LING_REALTIME_PROVIDER` 可指定默认 provider。未指定或指定项不可用时，代码按以下顺序选择已配置项：

```text
Gemini -> StepFun -> 火山 RTC -> MiniCPM-o
```

旧调试台可以在可用 provider 之间切换。切换 MiniCPM 的音频/视频模式会重连上游传输层，但继续使用同一个 Ling 业务会话。

## Gemini 音色预设

Gemini 默认使用 `cloudlet`（小云朵），另有 `starlight`（小星星）、`moonlamp`（月亮灯）和 `honeydrop`（蜂蜜糖）。每个 profile 在后端固定映射到预置 voice、风格 instruction 和静态试听 WAV；前端只能提交 profile ID，不能透传任意上游 voice 配置。

旧调试台会把选择保存在 `localStorage`，并在 Gemini WebSocket 建连时携带 `voice_profile`。选择仅在下一次建连生效，通话中不可更改。未传、非法或已删除的 ID 回退到 `cloudlet`。服务端默认值可用 `LING_GEMINI_VOICE_PROFILE` 调整；`LING_GEMINI_VOICE` 仅供 `legacy` 兼容模式使用。

试听文件由 `scripts/generate_voice_previews.py` 通过真实 `gemini-3.1-flash-live-preview` 会话生成，格式为 24 kHz、mono、16-bit PCM WAV。生成 manifest 记录模型、统一台词、转写、时长和 SHA-256。

## 会话契约

```text
POST /api/session/start
  -> session_id, opening, review_items

WS /api/realtime/ws?session_id=...&provider=gemini|stepfun|minicpm&video=0|1
  Gemini 可附加 &voice_profile=cloudlet|starlight|moonlamp|honeydrop
  或火山 /api/volcengine/prepare|start|observe|subtitle|stop

POST /api/session/end
  -> 同步冷路径结果和 moment 状态
```

当前 WebSocket 是浏览器 Demo 协议，媒体放在 JSON + Base64 中，不是正式硬件协议。会话状态主要在进程内；后端重启后不能恢复实时连接。

## 交互规则

- 开场只做纯问候；真实模型输出到达后才写入转写。
- Gemini 与 StepFun 支持每场最多两次受控冷场回应；计时主要在旧网页前端，后端保存预算。
- 火山复用同一预算，通过 `UpdateVoiceChat` 检查缓存画面。
- MiniCPM 不启用自动冷场回应。
- 孩子明确拒绝英语时，热路径立即进入 retreat，本场停止学习编织。

## 已知限制

- Gemini 集成 ASR 是附带转写，不保证逐字对应原生音频。
- Gemini profile 能稳定选择底声，但 Live API 没有公开数值化音高、语速或气息控制，风格细节会有回合波动。
- MiniCPM 当前没有用户侧转写，依赖用户文本的记忆和词汇记账不完整。
- StepFun 当前不发送视频。
- 火山必须使用“AI 音视频互动方案”应用，不能混用“实时对话式 AI”AppId。
- `websockets` 会读取系统代理变量；`wss://` 上游需要代理正确支持 CONNECT 与 WebSocket Upgrade。

## Change log

- `2026-07-11`：加入四个 Gemini 音色 profile、试听资产、白名单查询参数和默认回退规则。
- `2026-07-11`：从 2026-07-10 调研记录提取仍有效结论；加入 MiniCPM，删除账户、费用、提交号和排障过程等易过期内容。
