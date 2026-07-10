# 灵 Ling · ESP32 客户端接入架构与接口方案

> 面向硬件与后端共同实现。基于 2026-07-10 当前仓库代码整理。
>
> 文档中的接口分为两类：**现有兼容接口**今天即可联调；**Device API V1** 是建议冻结后实现的正式设备协议，目前代码中尚不存在。二者不要混用。

## 1. 结论先行

ESP32 不应直连 Gemini、StepFun 或火山引擎，也不应持有任何模型密钥。硬件只连接 Ling 后端：

```text
ESP32-S3
  |-- HTTPS：设备鉴权、创建/结束会话、获取配置
  `-- WSS：双向 PCM 音频、JPEG 画面、控制事件
          |
          v
Ling Device Gateway
  |-- Session Engine：记忆包、转写记账、撤退规则、正典
  |-- Provider Adapter：Gemini Live / StepFun
  `-- Cold Worker：日记、事实、掌握度、成长报告
```

正式硬件协议建议采用：

- 控制面：HTTPS + JSON。
- 媒体面：单条 WSS 长连接；控制消息用 JSON 文本帧，音频和图片用二进制帧。
- 固定设备侧音频基线：上行 `PCM S16LE / mono / 16 kHz`，下行 `PCM S16LE / mono / 24 kHz`；后端负责适配供应商采样率。
- 图片：JPEG，建议 `320x240`，最长边不得超过 `512 px`，最多 `1 FPS`，忙时直接丢帧。
- 会话生命周期、冷场计时、模型选择、记忆和冷路径全部归后端；板端只负责采集、播放和交互状态。

当前火山方案依赖浏览器 ByteRTC Web SDK，裸 ESP32 不能直接复用。第一版硬件应使用 Gemini 通道；纯音频备选 StepFun。若以后一定要使用火山 RTC，需要增加 Linux/云端 RTC 媒体桥或采用火山明确支持目标芯片的嵌入式 SDK，不能把当前 Web SDK 移植任务交给 ESP32。

## 2. ESP32 需要覆盖哪些前端功能

网页有六个视图，但实体玩偶只需接管“聊天页”的设备能力，其余继续留在网页/家长端。

| 网页功能 | ESP32 是否实现 | 归属与实现方式 |
|---|---:|---|
| 接通、挂断 | 是 | 创建会话、建立 WSS、结束会话 |
| 麦克风连续采集 | 是 | I2S + 环形缓冲区 |
| AI 语音播放 | 是 | WSS 下行 PCM + 播放抖动缓冲区 + I2S |
| 孩子开口打断 | 是 | AEC/VAD 检测后发送 `barge_in`；收到 `playback.clear` 立即清空播放队列 |
| 摄像头开关和画面输入 | 可选 | 摄像头板型发送 JPEG；无摄像头时在能力协商中声明不支持 |
| 双向字幕 | 可选 | 后端仍落盘；有屏幕的板子可显示 `transcript.final`，无屏幕直接忽略 |
| 今日编织进度 | 可选 | 可把 `state.updated` 映射到灯效，不在板端保存课程数据 |
| 冷场主动陪伴 | 是，但由后端控制 | ESP32 只上报说话/播放活动，不自行决定何时主动发言 |
| 模型切换 | 否 | 网页中的模型切换是演示功能；设备只声明能力，后端选 Provider |
| 初始化孩子/教材/人设 | 否 | 家长网页 |
| 灵灵的世界 | 否 | 网页与后端生活时钟 |
| 家长报告、事实删除 | 否 | 家长网页 |
| 夜间规划、反思、重置数据 | 否 | 后端任务/演示控制台 |

推荐第一版使用物理按键接通/挂断，摄像头必须有明确物理状态灯。唤醒词和常开监听不属于本次接口范围，可在媒体链路稳定后增加。

## 3. 当前后端：今天即可联调的兼容协议

### 3.1 适用范围与已知限制

当前网页协议可让硬件先跑通音频闭环，但只适合受控网络中的原型：

- 没有设备鉴权、账号鉴权和设备绑定。
- 全部请求固定使用 `CHILD_ID = 1`。
- `/api/session/start` 会把完整 `memory_pack` 返回客户端，其中可能含家庭和记忆信息；ESP32 必须忽略且不得记录。
- 媒体使用 JSON + Base64，比二进制多约 33% 带宽，并增加堆内存碎片风险。
- 会话运行状态保存在 Python 进程内；后端重启、多 worker 或长时间断线后不能恢复。
- `/api/session/end` 同步执行冷路径，可能耗时；接口还不是完全幂等。
- 冷场计时目前在浏览器中，硬件若要完全复刻现有体验也要临时实现计时。

因此该协议只用于 P0 联调，不能作为量产契约。

### 3.2 当前会话顺序

假设服务地址为 `https://<ling-host>`：

```text
1. POST /api/session/start
2. 取响应中的 session_id，忽略 memory_pack
3. WSS /api/realtime/ws?session_id=<session_id>&provider=gemini
4. 连续发送 Base64 PCM；可选发送 JPEG
5. 接收 PCM 并播放，按控制事件更新状态/打断
6. 先停止采集和播放并关闭 WSS
7. POST /api/session/end {"session_id":"..."}
```

创建会话：

```http
POST /api/session/start HTTP/1.1
Host: <ling-host>
Content-Length: 0
```

响应的稳定字段：

```json
{
  "session_id": "3f8db8faad31",
  "opening": "嗨，悠悠，灵灵在呢！",
  "memory_pack": {}
}
```

`opening` 仅供展示，实际欢迎语由实时模型自动生成；客户端不要再发 `response.create`，否则会重复问候。

连接实时通道：

```text
wss://<ling-host>/api/realtime/ws?session_id=3f8db8faad31&provider=gemini
```

当前 Provider 媒体格式：

| Provider | 上行 | 下行 | 图片 |
|---|---|---|---:|
| `gemini` | PCM S16LE、mono、16 kHz | PCM S16LE、mono、24 kHz | 支持 |
| `stepfun` | PCM S16LE、mono、24 kHz | PCM S16LE、mono、24 kHz | 不支持 |
| `volcengine` | 不走该 WSS | 不走该 WSS | 裸 ESP32 不可直接使用 |

建议 ESP32 每 `100 ms` 聚合一次 PCM，以匹配当前网页行为。以 Gemini 为例，每包原始音频 `3200 bytes`，Base64 后约 `4268 bytes`。

上行音频文本帧：

```json
{"type":"input_audio_buffer.append","audio":"<base64-pcm16le>"}
```

上行图片文本帧，建议 1 FPS、最长边 512 px：

```json
{"type":"ling.video_frame","mime_type":"image/jpeg","data":"<base64-jpeg>"}
```

可发送的其他事件：

```json
{"type":"response.cancel"}
{"type":"ling.idle_nudge"}
```

当前 `response.cancel` 只会转发给 StepFun；Gemini 代理会忽略该事件，Gemini 的打断依靠其服务端 VAD 检测持续上行的孩子语音。因此 P0 使用 Gemini 时，板端仍要持续上传麦克风 PCM，并在本地检测到孩子开口后立即停播，不能等待显式取消的确认。

`ling.idle_nudge` 每场最多发两次：模型一轮结束后第一次安静约 20 秒发送，第二次至少再间隔 45 秒。孩子开始说话、AI 开始回复或仍在播放时要取消计时。这个规则在 Device API V1 中会移到后端，板端不再实现。

主要下行事件：

| `type` | 关键字段 | ESP32 动作 |
|---|---|---|
| `session.created` / `session.updated` | `provider` | 进入已连接状态 |
| `input_audio_buffer.speech_started` | - | 清空播放队列，进入聆听状态 |
| `input_audio_buffer.speech_stopped` | - | 进入思考状态 |
| `response.created` | `id` | 建立一轮 AI 回复 |
| `response.audio.delta` | `delta` | Base64 解码为 PCM，放入播放缓冲区 |
| `response.done` | `response.id` | 该轮网络音频发送完成；需等本地缓冲播放完 |
| `conversation.item.input_audio_transcription.completed` | `transcript` | 可选显示；不得作为再次上行的文本 |
| `response.audio_transcript.delta/done` | `delta` / `transcript` | 可选显示 |
| `ling.state` | `woven`、`produced`、`retreated` 等 | 可选更新灯效/调试 UI |
| `ling.error` | `message` | 停止本次连接并按错误策略处理 |
| `error` | 上游错误 | 记录诊断；不一定代表连接必须断开 |

结束会话：

```http
POST /api/session/end HTTP/1.1
Content-Type: application/json

{"session_id":"3f8db8faad31"}
```

这个请求可能等冷路径模型完成后才返回。ESP32 不需要展示返回的日记/事实结果，但当前实现必须等 HTTP 请求完成或超时后释放请求资源；不要因为超时重复创建另一场会话。

## 4. 正式架构：Device API V1

### 4.1 服务边界

```text
                  +-------------------------+
ESP32 --HTTPS/WSS-| Device API / Gateway    |
                  +------------+------------+
                               |
                  +------------v------------+
                  | Session Service         |
                  | 持久状态、幂等、重连窗口 |
                  +---+------------------+--+
                      |                  |
             +--------v--------+  +------v----------------+
             | Provider Adapter|  | Transcript / Memory   |
             | Gemini / StepFun|  | Engine + Cold Worker  |
             +-----------------+  +-----------------------+
```

设备网关只做协议、鉴权、限流、媒体队列和采样率适配。记忆包只在后端流转，不返回设备。现有 `engine.py`、`memory.py`、`workers.py` 继续作为业务核心。

### 4.2 设备身份与绑定

原型阶段可为每块板配置独立静态 Bearer Token；正式版建议每台设备出厂写入：

- `device_id`：不可变公开标识。
- `device_secret`：32 字节随机值，存储在加密 NVS/安全区域，不出现在日志和固件仓库。

设备通过 TLS 下的 challenge-response 换取 15 分钟访问令牌，避免设备没有准确时钟时无法签名：

```http
POST /api/device/v1/auth/challenge
Content-Type: application/json

{"device_id":"ling-s3-01HXYZ"}
```

```json
{
  "challenge_id": "01J...",
  "nonce": "<base64url-random>",
  "expires_in": 60
}
```

证明值定义为：

```text
base64url_without_padding(
  HMAC-SHA256(
    device_secret,
    UTF8("ling-device-v1\n" + device_id + "\n" + challenge_id + "\n" + nonce)
  )
)
```

```http
POST /api/device/v1/auth/token
Content-Type: application/json

{
  "device_id":"ling-s3-01HXYZ",
  "challenge_id":"01J...",
  "proof":"<base64url-hmac>"
}
```

```json
{
  "access_token":"<opaque-or-jwt>",
  "token_type":"Bearer",
  "expires_in":900,
  "server_time":"2026-07-10T12:00:00Z",
  "claimed":true
}
```

家长绑定设备是另一个受家长账号保护的流程，不应由 ESP32 传 `child_id`。后端根据 Token 中的 `device_id -> household_id -> child_id` 映射决定使用哪套记忆。未绑定设备只能获取绑定码，不能创建会话。

### 4.3 获取设备配置

```http
GET /api/device/v1/config
Authorization: Bearer <access_token>
```

```json
{
  "device_id":"ling-s3-01HXYZ",
  "claimed":true,
  "features":{"camera":true,"transcript":false},
  "limits":{"max_session_seconds":3600,"max_jpeg_bytes":100000},
  "firmware":{"minimum_version":"0.1.0","update_required":false}
}
```

配置不返回孩子姓名、家庭、事实、课程词或模型密钥。

### 4.4 创建会话

```http
POST /api/device/v1/sessions
Authorization: Bearer <access_token>
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
Content-Type: application/json

{
  "firmware_version":"0.1.0",
  "capabilities":{
    "audio_input":[{"encoding":"pcm_s16le","sample_rate":16000,"channels":1}],
    "audio_output":[
      {"encoding":"pcm_s16le","sample_rate":24000,"channels":1},
      {"encoding":"pcm_s16le","sample_rate":16000,"channels":1}
    ],
    "camera":{"available":true,"formats":["jpeg"],"max_width":512,"max_height":512},
    "aec":true,
    "local_vad":true
  }
}
```

`Idempotency-Key` 由板端每次物理“接通”生成并持久到本次流程结束。HTTP 超时后必须用同一个 Key 重试，后端返回同一场会话。

```json
{
  "session_id":"01J2SESSION...",
  "status":"created",
  "stream_url":"wss://<ling-host>/api/device/v1/sessions/01J2SESSION.../stream",
  "stream_token":"<session-scoped-token>",
  "stream_token_expires_in":60,
  "protocol":"ling.device.v1",
  "negotiated":{
    "audio_input":{"encoding":"pcm_s16le","sample_rate":16000,"channels":1,"packet_ms":40},
    "audio_output":{"encoding":"pcm_s16le","sample_rate":24000,"channels":1},
    "video_input":{"encoding":"jpeg","max_width":512,"max_height":512,"max_fps":1,"max_bytes":100000}
  },
  "heartbeat_interval_ms":15000,
  "reconnect_grace_ms":30000
}
```

模型 Provider 不属于设备契约，响应中可以提供只读 `diagnostics.provider` 方便开发调试，但固件不得按供应商写分支。

### 4.5 刷新流令牌与查询会话

流令牌只允许访问指定设备的指定会话。初次连接失败或重连时，可用访问令牌刷新：

```http
POST /api/device/v1/sessions/{session_id}/stream-token
Authorization: Bearer <access_token>
```

```json
{"stream_token":"<new-session-token>","expires_in":60}
```

查询状态：

```http
GET /api/device/v1/sessions/{session_id}
Authorization: Bearer <access_token>
```

```json
{
  "session_id":"01J2SESSION...",
  "status":"active",
  "stream_connected":true,
  "cold_path_status":"not_started"
}
```

### 4.6 结束会话

```http
POST /api/device/v1/sessions/{session_id}/end
Authorization: Bearer <access_token>
Idempotency-Key: 838e8400-e29b-41d4-a716-446655440000
Content-Type: application/json

{"reason":"user_hangup","last_client_seq":18342}
```

```http
HTTP/1.1 202 Accepted
```

```json
{
  "session_id":"01J2SESSION...",
  "status":"processing",
  "cold_path_status":"queued"
}
```

结束接口必须幂等。设备收到 `202` 后即可熄灭通话状态或休眠，不等待日记、事实和掌握度计算。冷路径结果由家长网页读取。

## 5. Device WebSocket V1

### 5.1 握手与连接状态

```text
GET /api/device/v1/sessions/{session_id}/stream
Authorization: Bearer <stream_token>
Sec-WebSocket-Protocol: ling.device.v1
```

连接成功后，设备先发：

```json
{
  "type":"hello",
  "protocol":"ling.device.v1",
  "connection_id":"550e8400-e29b-41d4-a716-446655440000",
  "firmware_version":"0.1.0"
}
```

后端回复后才允许发送媒体：

```json
{
  "type":"ready",
  "session_id":"01J2SESSION...",
  "resumed":false,
  "client_seq_base":0,
  "server_seq_base":0
}
```

会话状态机：

```text
IDLE -> AUTHENTICATING -> CREATING -> CONNECTING -> ACTIVE
                                                   |  |
                                      network loss |  | hangup/fatal
                                                   v  v
                                            RECONNECTING -> ENDING
                                                               |
                                                               v
                                                              IDLE
```

WSS 断开不等于结束业务会话。30 秒重连窗口内，板端刷新流令牌并重连同一个 `session_id`；不重发旧音频或旧图片。后端保留转写与业务状态，重新建立上游模型连接时注入 L0 最近对话。超过窗口后，后端自动结束并排队冷路径。

### 5.2 文本控制帧

设备到后端：

| `type` | 字段 | 说明 |
|---|---|---|
| `hello` | 见上文 | 每条新 WSS 的第一条消息 |
| `ping` | `id`、`client_time_ms` | 应用层心跳；收到 `pong` 前不要累计多次 |
| `audio.input.started` | `client_seq` | 本地 VAD 检测到说话；没有本地 VAD 可不发 |
| `audio.input.stopped` | `client_seq` | 本地 VAD 检测到停顿 |
| `barge_in` | `client_seq` | 孩子在 AI 播放时开口，请求立刻取消回复 |
| `playback.started` | `response_id` | 本地真正开始播放，不是仅收到网络数据 |
| `playback.ended` | `response_id` | 本地抖动缓冲播放完毕 |
| `camera.state` | `enabled` | 物理摄像头状态变化 |
| `session.end` | `reason`、`last_client_seq` | WSS 内快速挂断；板端随后仍调用幂等 HTTP end |

后端到设备：

| `type` | 字段 | 设备动作 |
|---|---|---|
| `ready` | 见上文 | 开始采集和发送 |
| `pong` | `id`、`server_time_ms` | 更新连接健康状态 |
| `user.speech.started` | - | 显示聆听状态 |
| `user.speech.stopped` | - | 显示思考状态 |
| `assistant.response.started` | `response_id` | 建立下行播放轮次 |
| `assistant.response.stopped` | `response_id`、`reason` | 网络侧该轮结束；本地继续播完队列 |
| `playback.clear` | `response_id`、`reason` | 立即停止 I2S 当前块并清空该轮未播 PCM |
| `transcript.final` | `role`、`text`、`turn_id` | 可选显示，忽略不会影响功能 |
| `state.updated` | `retreated`、`shared` 等 | 可选灯效/调试；板端不持久化 |
| `flow_control` | `video_allowed`、`max_video_fps` | 禁止视频时立即停发；音频优先 |
| `error` | `code`、`message`、`retryable` | 按错误分类重连或结束 |
| `session.ending` | `reason` | 停采集、清播放、进入结束流程 |

所有未知 JSON `type` 必须忽略，以保证协议可向前扩展。控制帧建议限制在 `8 KiB` 内。

### 5.3 二进制媒体帧

WebSocket 二进制消息由 20 字节头和 payload 组成。多字节头字段使用网络字节序；PCM payload 固定为小端。

```text
Offset  Size  Field
0       2     magic = ASCII "LG"
2       1     version = 1
3       1     kind
4       2     flags
6       2     header_len = 20
8       4     seq
12      4     timestamp_ms（发送方启动后的单调时钟，允许回绕）
16      4     payload_len
20      N     payload
```

`kind`：

```text
0x01  AUDIO_UP    ESP32 -> 后端，格式来自 negotiated.audio_input
0x02  AUDIO_DOWN  后端 -> ESP32，格式来自 negotiated.audio_output
0x03  JPEG_UP     ESP32 -> 后端
```

`flags`：

```text
0x0001  START_OF_SEGMENT
0x0002  END_OF_SEGMENT
0x0004  DISCONTINUITY（本地溢出、重连或丢弃过音频）
```

`seq` 在每个方向全局单调递增，回绕按无符号 32 位处理。`timestamp_ms` 使用各自发送方的单调时钟，只能计算同一方向内的间隔，不能拿设备值和服务器值直接相减。WebSocket 本身保证单连接内有序；序号用于诊断、去重和识别重连边界，不要求重放。

限制：

- `AUDIO_UP` 正常每包 `40 ms`。16 kHz、mono、S16LE 时 payload 恰好 `1280 bytes`。
- `AUDIO_DOWN` 可以是任意整采样点长度，板端统一写入抖动缓冲区。
- JPEG 不超过会话协商的 `max_bytes`，不得拆成多个应用层帧。
- `payload_len` 与 WebSocket 消息实际剩余长度不一致时，接收方关闭连接并报告 `PROTOCOL_ERROR`。
- 不要把 C packed struct 直接强转网络字节流；逐字段编解码，避免对齐和端序问题。

### 5.4 心跳、流控与打断

- ACTIVE 状态每 15 秒发一次 `ping`，45 秒未收到任何后端消息视为断线。
- 音频发送队列上限建议为 500 ms；网络拥塞时先丢 JPEG，再丢最旧音频，并给下一包加 `DISCONTINUITY`。
- JPEG 不排队，只保留最新一帧。
- 下行 PCM 建议保留 120-200 ms 抖动缓冲；实际值由板端音频稳定性测试决定。
- 本地 VAD 在 AI 播放时检测到人声，应立即降低/停止扬声器、发送 `barge_in`，并继续上传麦克风 PCM。
- 收到 `playback.clear` 后不能播放队列中该回复的尾音。`response.stopped` 不等于 `playback.clear`。
- 无可靠 AEC 时，不要宣称全双工打断可用；P0 应切换为按键说话或半双工，防止扬声器回声持续触发模型。

## 6. 标准错误格式

HTTP 非 2xx：

```json
{
  "error":{
    "code":"DEVICE_NOT_CLAIMED",
    "message":"device is not bound to a child profile",
    "retryable":false,
    "request_id":"01J2REQ..."
  }
}
```

建议错误码：

| Code | 是否重试 | 处理 |
|---|---:|---|
| `UNAUTHORIZED` | 是 | 重新换 Token；连续失败进入配网/维修状态 |
| `DEVICE_NOT_CLAIMED` | 否 | 提示家长完成绑定 |
| `FIRMWARE_TOO_OLD` | 否 | 进入 OTA 流程 |
| `SESSION_ALREADY_ACTIVE` | 否 | 查询并恢复现有会话，不新建 |
| `SESSION_NOT_FOUND` | 否 | 回到 IDLE；必要时创建新会话 |
| `PROVIDER_UNAVAILABLE` | 是 | 指数退避，后端可自动切备用 Provider |
| `RATE_LIMITED` | 是 | 按 `retry_after_ms` 等待 |
| `PROTOCOL_ERROR` | 否 | 结束会话并记录固件版本和协议诊断 |
| `INTERNAL_ERROR` | 是 | 有上限地指数退避 |

建议 WSS 关闭码：`4401` 鉴权失败、`4404` 会话不存在、`4409` 同设备已有连接、`4429` 限流、`4500` 后端错误。关闭原因只写机器可识别错误码，不放孩子数据或模型返回内容。

## 7. ESP32 端建议模块

建议目标硬件为带 PSRAM 的 ESP32-S3；具体 RAM、音频 codec、麦克风阵列和摄像头型号必须由硬件同伴确认后再锁定。

```text
device_manager_task
  Wi-Fi / TLS / 鉴权 / 会话状态机 / 指数退避

audio_capture_task
  I2S RX -> AFE(AEC/NS/AGC/VAD) -> 固定块环形缓冲区

media_tx_task
  聚合 40 ms PCM -> WSS；低优先级发送最新 JPEG

ws_rx_task
  回调中只校验并入队，不做 I2S 写入和大块 JSON 处理

audio_playback_task
  下行 PCM 抖动缓冲 -> I2S TX；处理 playback.clear

camera_task（可选）
  低分辨率 JPEG -> 单帧槽；网络忙时覆盖旧帧

ui_task
  按键、灯、屏幕；只消费状态事件
```

硬件端原则：

- 音频路径使用预分配内存和固定大小队列，避免通话中反复 `malloc/free`。
- TLS、JPEG 和音频缓冲都吃内存，摄像头板型应启用 PSRAM；仍要给 AEC/网络栈留出余量。
- WebSocket 回调不得阻塞。收到音频只做校验和队列投递。
- 不缓存完整转写、记忆包或会话音频；设备重启后只保留身份、绑定状态和未完成的幂等 Key。
- Token、challenge、HMAC 和日志缓冲不得打印 `device_secret`。
- 固件必须支持“无摄像头”“无本地 VAD”“只能 16 kHz 播放”等能力降级，最终格式以创建会话响应为准。

## 8. 后端需要补的模块

建议在不破坏现有网页的前提下增量实现：

```text
backend/device_api.py       鉴权、配置、会话 HTTP API
backend/device_gateway.py   Device WSS、二进制帧、队列、心跳
backend/device_protocol.py  帧编解码、错误码、能力协商
backend/providers/          统一 Gemini / StepFun Adapter
backend/session_service.py  持久会话、幂等、重连与冷路径排队
```

现有代码需要解决的关键点：

1. `CHILD_ID = 1` 改为从设备绑定关系解析，所有查询继续显式传 `child_id`。
2. `engine.SESSIONS` 的必要状态持久化；至少包括公开 session ID、业务状态、编织状态、冷场预算和最近 L0 转写。
3. WebSocket 重连重新建立 Provider 时，注入最近几轮 L0，不能重复欢迎语。
4. Device Gateway 统一对设备暴露 16 kHz 上行；StepFun 的 24 kHz 输入在后端重采样。
5. 冷场计时从浏览器移到后端，并以“孩子最终转写、AI 回复完成、本地 playback.ended”共同更新活动时间。
6. `/end` 先原子标记结束、再投递幂等冷路径任务，立即返回 `202`。
7. SQLite 可保留给单机 demo；多进程/多实例前将活跃会话放 Redis 或数据库，把冷路径放任务队列。
8. Provider API key、设备 secret、流 Token 全部做日志脱敏；指标只带匿名 device/session ID。

建议统一 Provider Adapter 内部接口：

```text
open(session_context, event_sink)
send_audio(pcm16, sample_rate)
send_video(jpeg)
cancel_response()
close(reason)
```

Provider 产生的音频、VAD、转写和错误先归一化为内部事件，再由网页协议或 Device V1 各自编码。这样网页和硬件共用业务状态，不复制记忆逻辑。

## 9. 分阶段交付

### P0：先让板子说起来

- 明确使用 ESP32-S3、麦克风/codec/扬声器/摄像头型号。
- 后端配置 Gemini，板端使用第 3 节现有 JSON + Base64 协议。
- 先做按键接通/挂断、16 kHz 上行、24 kHz 下行；无 AEC 时先半双工。
- 图片最后接，先验证连续 10 分钟音频不溢出。
- 仅在隔离测试环境使用，不能把无鉴权接口直接暴露公网。

### P1：冻结并实现 Device API V1

- 设备身份、家长绑定、幂等会话。
- 二进制媒体帧、固定设备采样率、服务端冷场控制。
- 断线 30 秒内恢复、异步结束和标准错误码。
- Gemini 主通道、StepFun 纯音频回退。

### P2：量产准备

- AEC/NS/AGC 实机调优，弱网与路由器兼容测试。
- 安全启动、Flash/NVS 加密、每机密钥注入、OTA 和吊销。
- Redis/任务队列、多实例、限流、指标和告警。
- 明确摄像头启用提示、家长控制与数据保留策略。

## 10. 联调验收清单

以下全部通过，才算复刻了网页聊天核心能力：

1. 同一个接通动作即使 HTTP 超时重试，也只创建一条后端会话。
2. 建连后只播放一次欢迎语，模型切换/短线重连不重复欢迎。
3. 连续通话 10 分钟无 I2S underrun、音频发送队列持续增长或明显堆内存下降。
4. AI 说话时孩子开口，设备能停止尾音并继续上传孩子语音；实测并记录打断延迟。
5. 中英文混说的上行采样率、端序正确，播放速度和音调正确。
6. 打开摄像头后每秒最多一帧；拥塞时图片被丢弃，音频不断。
7. Wi-Fi 中断 10 秒后恢复同一业务会话，不重复冷路径、不丢已落盘转写。
8. 主动挂断立即退出通话状态，后端最终只生成一份日记和一份冷路径结果。
9. Provider 不可用、Token 失效和协议错误有不同灯效/日志与重试策略。
10. 设备日志、反代日志和错误上报中不存在模型密钥、设备 secret、家庭信息和完整记忆包。

## 11. 开工前必须确认的硬件信息

硬件同伴回复以下信息后，才能把板端参数和 ESP-IDF 组件版本锁死：

- 开发板准确型号、ESP32 芯片型号、Flash/PSRAM 容量。
- 麦克风类型和数量、音频 codec/功放型号、I2S 引脚与支持采样率。
- 是否具备经过验证的 AEC；若没有，第一版接受半双工还是必须采购/更换音频方案。
- 摄像头型号、是否支持硬件 JPEG、可稳定输出的分辨率和单帧大小。
- 是否有屏幕、RGB 灯、物理接通/挂断/静音/摄像头按键。
- 供电方式和目标连续工作时长。
- 使用 ESP-IDF 还是 Arduino；正式版建议 ESP-IDF，具体版本由现有 BSP 和音频组件共同决定。
- 联调后端域名、TLS 证书链、测试设备 ID，以及首选 Provider 是否确定为 Gemini。

这组信息未确定前，后端可以先实现协议编解码和模拟客户端，板端可以先完成 I2S loopback、固定块音频队列与 HTTPS/WSS 基础连接。
