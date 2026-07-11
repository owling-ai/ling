# ESP32 Device API 提案

状态：**未实现**。更新：2026-07-11。

本文只保留硬件接入边界和建议协议。当前代码没有 `/api/device/v1/*`、设备身份、绑定、二进制媒体帧或断线恢复。

## 当前可做的 P0 原型

ESP32 可在隔离网络中复用浏览器 Demo 协议：

```text
POST /api/session/start
WS   /api/realtime/ws?session_id=<id>&provider=gemini|stepfun|minicpm
     Gemini 可选 &voice_profile=cloudlet|starlight|moonlamp|honeydrop
POST /api/session/end
```

Gemini 未传或传入非法 `voice_profile` 时使用 `cloudlet`，因此设备端可以完全不增加配置字段。

当前响应和限制：

- `session/start` 返回 `session_id`、`opening`、`review_items`，不返回完整记忆包。
- WebSocket 使用 JSON + Base64，不适合量产带宽和内存预算。
- Gemini：16 kHz PCM16 上行、24 kHz PCM16 下行、可发 JPEG。
- StepFun：24 kHz PCM16 双向、无视频。
- MiniCPM：设备仍按 16 kHz PCM16 上行，后端负责协议和格式转换；当前无用户 ASR。
- 火山方案依赖浏览器 ByteRTC SDK，裸 ESP32 不能复用。
- 固定 `CHILD_ID=1`，没有设备鉴权或绑定。
- `/api/session/end` 同步运行冷路径，可能耗时。
- 实时会话主要保存在进程内，重启后不可恢复。

P0 仅用于验证 I2S、采集、播放和网络链路。没有可靠 AEC 时使用按键说话或半双工，不宣称全双工打断。

## 正式边界

ESP32 不直连模型，不持有模型 key。只连接 Ling Device Gateway：

```text
ESP32 -- HTTPS/WSS --> Device Gateway --> Session / Memory Engine
                                  `----> Provider Adapter
```

建议基线：

- 控制面：HTTPS + JSON。
- 媒体面：一条 WSS；控制用 JSON 文本帧，媒体用二进制帧。
- 上行：PCM S16LE、mono、16 kHz、40 ms/包。
- 下行：PCM S16LE、mono、24 kHz。
- 图片：JPEG，最长边 512px，最多 1 FPS；拥塞时先丢图。
- 会话生命周期、provider 选择、冷场预算、记忆和冷路径全部在后端。

## 建议 API V1

```text
POST /api/device/v1/auth/challenge
POST /api/device/v1/auth/token
GET  /api/device/v1/config
POST /api/device/v1/sessions
GET  /api/device/v1/sessions/{id}
POST /api/device/v1/sessions/{id}/stream-token
POST /api/device/v1/sessions/{id}/end
WS   /api/device/v1/sessions/{id}/stream
```

关键约束：

1. 每台设备使用独立 `device_id` 与 secret；Token 映射到家庭和孩子，设备不提交 `child_id`。
2. 创建和结束会话必须接受 `Idempotency-Key`。
3. 流 Token 只允许访问单个设备的单场会话，短期有效。
4. WSS 断开不等于结束；建议保留 30 秒重连窗口。
5. 结束接口立即返回 `202`，冷路径异步执行。
6. Provider 不属于固件契约；固件按协商后的采样率和能力工作。
7. 未知 JSON 事件必须忽略，保证协议可扩展。

## 二进制帧建议

```text
Offset  Size  Field
0       2     magic = "LG"
2       1     version = 1
3       1     kind: AUDIO_UP | AUDIO_DOWN | JPEG_UP
4       2     flags
6       2     header_len = 20
8       4     seq
12      4     timestamp_ms
16      4     payload_len
20      N     payload
```

多字节头字段使用网络字节序；PCM payload 保持小端。逐字段编解码，不直接强转 packed struct。

## 后端待实现

- 设备身份、家长绑定、令牌吊销和日志脱敏。
- 持久会话、幂等创建/结束、重连与异步冷路径。
- 二进制帧、队列、心跳、流控和采样率转换。
- 归一化 Provider Adapter；网页与设备共享业务状态，不复制记忆逻辑。
- 多实例前引入共享会话存储和任务队列。

## 板端验收

- 连续 10 分钟无 I2S underrun、队列增长或明显堆内存下降。
- 打断能停止尾音；记录端到端延迟。
- Wi-Fi 短断后恢复同一业务会话，不重复欢迎和冷路径。
- 拥塞时图片先丢，音频连续。
- 日志不含模型 key、设备 secret、家庭信息、完整转写或记忆数据。

## Change log

- `2026-07-11`：按当前代码修正 `session/start` 响应，加入 MiniCPM；删除把建议协议写成现有能力的内容，压缩为明确的未实现提案。
