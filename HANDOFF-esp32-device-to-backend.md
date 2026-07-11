# Handoff：ESP32 设备端 → 后端待修事项

日期：2026-07-11 晚
来源：ESP32-S3 固件调试会话（Claude Code，项目 `~/Downloads/esp32s3_audio_llm`）
读者：在 `~/workspace/ling` 工作的 Codex / 后端维护者

## TL;DR

设备端断线自愈、打断、打招呼静音已全部实现并验证工作。剩余四个问题都在后端（`backend/`，跑在本机 8888 端口），按优先级：

1. **重连后会话上下文丢失** —— 设备复用 session_id 重连后，模型像新对话一样重新打招呼/自我介绍（用户实际听感："又重说了"）
2. **Gemini Live 上游连接不稳定** —— 这是设备频繁断线的直接诱因
3. **进程健壮性** —— 今晚 20:31 左右后端进程整个挂死过一次，需要人工重启
4. 可选增强：response.cancel、帧大小上限、opening 推送语义

## 架构与环境

- 设备：立创实战派 ESP32-S3，固件在 `~/Downloads/esp32s3_audio_llm`（ESP-IDF v5.4 本机构建，`idf.py -B build_mac build`）
- 后端：`uv run uvicorn backend.app:app --host 0.0.0.0 --port 8888`，日志 `/private/tmp/ling-8888.log`
- 协议：HTTP `POST /api/session/start` → `WS /api/realtime/ws?session_id=X&provider=gemini`，OpenAI Realtime 风格 JSON 事件，音频 Base64 PCM
- 设备串口实时日志：`~/Downloads/esp32s3_audio_llm/serial_capture.log`（后台 logger 持续写入，带本地时间戳）

## 已实证的事实（都有日志佐证）

### 1. 后端每次 WS 连接建立都自动推 opening（打招呼）

直连探测脚本验证（三组实验）：新建 session 首连会推 `response.created` + 打招呼音频；**复用同一 session_id 重连也照样推**；空闲 120 秒不发数据服务器不断连。

设备端对策（已上线）：自动重连（resume）后的第一条自动 response 整段静音丢弃。但这只能压掉自动推送的 opening——见下一条。

### 2. 重连后模型上下文丢失，第一句真实回复会重新自我介绍

设备日志 20:46-20:48 段：断线 → 设备复用 session_id 重连成功 → 自动 opening 被设备静音 → 用户提问 → 模型的**真实回复**内容仍是重新打招呼式的（上下文全新）。

**期望的后端行为**：同一 session_id 重连时，把会话历史恢复进新的 Gemini Live 上游（历史回放或 Gemini session resumption token），并且不要重新触发 opening。这是"又重说了"的根治点。

### 3. 断线诱因：Gemini Live 上游连接失败

设备日志 20:46:42：

```
[错误] 无法连接 Gemini Live，请检查网络与代理
WS read 错误: -2 (errno=128, ...)
```

后端发出 `ling.error` 后直接关闭了设备 WS。之后还观察到服务器静默 15 秒以上不发任何消息（设备看门狗兜底拉回聆听）。上游代理/网络配置值得排查；另外上游失败时建议后端别直接杀设备连接，发错误事件让设备保持连接重试更平滑。

### 4. 后端进程今晚整个挂死过一次（约 20:31）

`/private/tmp/ling-8888.log` 中有两处：

```
ERROR:    Invalid UTF-8 sequence received from client.
...
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xf0 in position 2
```

原因链：设备 WiFi 拥堵时 WS 帧只写出一半，旧固件继续在错位的字节流上发送，服务器把帧头当正文解码。**设备端已修复**（发送失败立即断链重连，不再喂垃圾）。但 uvicorn 对单连接的解码错误按 RFC 关连接是正常的；问题是之后整个进程对新连接直接 RST（彻底死掉，需要人工重启）。值得查：单连接异常是否泄漏/卡死了什么全局资源（如 Gemini 上游句柄、asyncio task）。

## 设备端协议契约（后端改动时别破坏）

上行（设备 → 后端）：
- `{"type":"input_audio_buffer.append","audio":"<b64>"}` —— 16kHz mono S16LE，每 100ms 一帧（3200 字节 PCM）
- `{"type":"response.cancel"}` —— 用户按键打断时发送（新功能）。后端若能取消当前回复并停止推流最好；忽略也不出错（设备本地已静音丢弃）
- WS PING：设备空闲 >20s 会发空 payload PING；也会应答服务器 PING（回 PONG）

下行（后端 → 设备）约束：
- **单个 WS 帧 ≤ 64KB**（设备接收缓冲上限，超了整帧丢弃并断链重连）。目前观测最大 28KB，安全
- 设备依赖的事件：`session.created`、`response.created`、`response.audio.delta`、`response.done`、`input_audio_buffer.speech_started/stopped`、`ling.error`。**`response.done` 千万别省**——设备靠它恢复麦克风（虽有 15 秒看门狗兜底）
- `response.audio.delta`：24kHz mono S16LE Base64

## 设备端已修复项（Codex 不用管，列出防重复排查）

跳字/卡顿（接收缓冲 64KB、播放队列 64+预缓冲、分片重组失败断链）、永久沉默（状态看门狗）、断线自动重连（复用 session_id + opening 静音）、发送失败流损坏断链、按键语义（单击打断/长按挂断）、上行独立发送任务。

## 验证方法

1. 设备正常对话中，后端 `kill -9` 再重启 → 设备 3-4 秒内自动重连；**验收点：重连后 AI 不重新打招呼，且还记得之前聊了什么**
2. AI 说话时单击设备 BOOT 键 → 后端应收到 `response.cancel`
3. 长时间对话中观察 `/private/tmp/ling-8888.log` 无 UnicodeDecodeError（设备端已保证不发坏帧）
