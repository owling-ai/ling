# Ling 原生童声音色方案

> 验证日期：2026-07-11
>
> 当前实现：Gemini 文本模型 + ByteRTC + 豆包语音合成大模型 2.0

## 1. 结论

旧版“小云朵 / 小星星 / 月亮灯 / 蜂蜜糖”已经移除。它们只是 Gemini 成人预置声线加角色提示，严格听感评审仍属于成年人装嫩，不能继续称为童声。

当前只保留两档通过真实 RTC 链路和跨情绪验证的原生童声：

| Profile | 服务端 voice | 听感年龄 | 评审结果 |
|---|---|---:|---|
| `sunny` / 小晴天 | `zh_male_tiancaitongsheng_uranus_bigtts` | 6-8 岁 | 通过 |
| `sprout` / 小青芽 | `ICL_uranus_zh_female_jiaxiaozi_tob` | 7-9 岁 | 通过 |

两档都来自火山引擎官方 `seed-tts-2.0` 公版目录，未使用真人儿童录音、声音复制、DSP 升调或共振峰变换。前端只能提交 profile ID，不能透传任意 voice、模型版本或 TTS 参数。

## 2. 为什么不能继续使用 Gemini Live 预置 voice

Gemini Live 当前公开能力只能在预置 voice 中选择基础声线，并用自然语言限制语气。实际测试包括：

- Gemini TTS 直接提示“8 岁自然中国儿童”；
- `Leda`、`Puck`、`Achird`、`Zephyr`、`Autonoe` 等基础声线；
- `1.08-1.20` 倍音高和共振相关处理；
- 多轮匿名听感评审。

严格评审仍能听出成人声带底色、成熟咬字、夹嗓、卡通化或变调伪影。提示词可以改变表演方式，不能把成年人的声道和共鸣结构变成儿童。

Gemini Live 的实验 `replicatedVoiceConfig` 也没有作为替代：

- 公开产品文档仍未完整说明支持范围；
- 缺少合法成年声音提供者的参考录音、授权录音和授权签名；
- 不允许复制儿童、卡通角色或权利来源不明的第三方声音；
- 不能把另一家供应商的公版 voice 重新克隆进 Gemini。

## 3. 当前实时架构

为了保留 Gemini API，同时获得真正的童声，实时链路改为：

```text
浏览器麦克风/摄像头
  -> ByteRTC WebRTC
  -> 火山流式 ASR、VAD、语音打断、视频抽帧
  -> Ling 的鉴权 SSE 回调
  -> Gemini OpenAI-compatible streaming API
  -> 火山双向流 seed-tts-2.0
  -> ByteRTC 下行音频与字幕
```

关键实现：

- `backend/voice_profiles.py`：服务端童声白名单和默认回退；
- `backend/volcengine_rtc.py`：RTC 任务、Gemini CustomLLM 配置、TTS profile 和 OpenAI payload 过滤；
- `POST /integrations/volcengine/gemini`：只供火山云端调用的 SSE 适配端点；
- `frontend/assets/app.js`：试听、单选、持久化和通话中锁定；
- `frontend/assets/voices/manifest.json`：公开试听来源、profile、哈希和评审结果，不包含上游 voice ID。

这不是 Gemini Live 原生音频到音频模式。它保留了 Gemini 模型、流式响应、语音打断和视频理解能力，但需要 ASR、文本模型和 TTS 级联。2026-07-11 的三次本机到云端真实测试中，从服务端触发到完整回复字幕为 `2.2-3.7s`；其中一次无视频测试检测到首个非静音下行音频约 `2.58s`。这些数字不能宣传成 Gemini Live 原生首包延迟。

## 4. Profile 约束

两个 profile 都固定使用以下 TTS 原生上下文：

> 请用自然、放松、生活化的日常语气说话，减少表演感。不要夹嗓，不要使用夸张卡通腔，不要故意拖长尾音。像一个八九岁的小朋友跟熟悉的同伴正常聊天。

该约束通过 `VolcanoTTSParameters.req_params.context_texts` 随 RTC 任务持续生效，不修改音高，也不做播放端后处理。

默认 profile 为 `sunny`。环境变量 `LING_VOLC_VOICE_PROFILE` 只接受 `sunny` 或 `sprout`；未传、非法或已经删除的 ID 都回退到 `sunny`。profile 在 `/api/volcengine/prepare` 时绑定，通话中不能切换。

## 5. 评审方法

### 5.1 目录筛选

通过火山 `ListSpeakers` 拉取 `seed-tts-1.0` 和 `seed-tts-2.0` 共 575 个 voice，先按供应商 `Age`、语言和描述筛选，再排除：

- 明显影射现成动画、游戏或卡通角色的 voice；
- “少女、学妹、女友”等恋爱向青年声；
- 少儿故事主持、成年幼教或客服声；
- 夸张卡通腔、夹子音和仅靠高音模拟幼儿的 voice。

供应商的“儿童”标签不是通过条件。多个官方标注儿童的 voice 在匿名评审中仍被判定为成年人装嫩或角色配音。

### 5.2 实际 RTC 样本

候选音频不是官网试听。浏览器实际加入 ByteRTC 房间，订阅 AI 远端音轨，并用 `ExternalTextToSpeech` 让生产 TTS 配置播报统一台词；录回 WebM 后转换为 24 kHz、单声道、16-bit PCM WAV。

最终 profile 还分别测试了三类文案：

1. 日常观察与提问；
2. 安慰孩子答错题；
3. 兴奋回应孩子画的恐龙。

只有跨文案保持儿童声道听感、低成人模仿风险和低卡通风险的候选才进入白名单。没有为了凑足四档而保留不稳定声线。

### 5.3 通过门槛

匿名评审使用 `gemini-3.1-pro-preview`，要求：

- `child_likeness >= 7`；
- `adult_imitation_risk <= 3`；
- `cartoon_risk <= 4`；
- `long_chat_comfort >= 7`；
- 听感年龄主要落在 6-11 岁；
- 普通话和中英切换自然；
- 无明显变调、电音、断句或链路伪影。

最终双语试听两档均得到：儿童听感 `8/10`、成人装嫩风险 `2/10`、卡通风险 `3/10`、普通话自然度 `8/10`、长聊舒适度 `8/10`、合成伪影 `2/10`。

试听文件由 `scripts/validate_voice_previews.py` 校验格式、时长、SHA-256、削波和评审门槛。

### 5.4 完整 ASR / 视频回路

最终实现另用 Chromium 假麦克风和假摄像头验证完整生产任务，而不是只调用外部文本播报：

- ASR 将测试输入完整定稿为“你好灵灵，你看得到我吗？我手里拿着什么颜色的东西？”；
- Gemini 在 ASR 定稿后约 `1.1s` 返回首段完整字幕；
- 回复继续说明“是亮亮的绿色”，与假摄像头画面一致，证明图片内容经过 CustomLLM 回调到达 Gemini；
- `sprout` 下行录音为有效 Opus 音轨，转为 WAV 后包含完整欢迎和回复语音；
- 测试中一次 Gemini 建连发生瞬时 `URLError`，火山重试后成功；当前后端也只在尚未建立 SSE 响应时短重试一次。

这组结果验证了 `ByteRTC ASR -> Gemini SSE -> seed-tts-2.0 -> ByteRTC`，但不代替真实儿童说话、家庭 Wi-Fi、回声消除和玩偶扬声器环境测试。

## 6. 配置

```bash
GEMINI_API_KEY=...
VOLCENGINE_RTC_APP_ID=...
VOLCENGINE_RTC_APP_KEY=...
VOLCENGINE_ACCESS_KEY=...
VOLCENGINE_SECRET_KEY=...

LING_VOLC_GEMINI_LLM_URL=https://ling.example.com/integrations/volcengine/gemini
LING_VOLC_GEMINI_MODEL=gemini-3.1-flash-lite
LING_VOLC_VOICE_PROFILE=sunny
LING_REALTIME_PROVIDER=volcengine
```

`LING_VOLC_GEMINI_LLM_URL` 必须是公网 HTTPS URL，并路由到运行当前进程的同一个 Ling 服务。若未配置，火山 RTC 回退到 Ark；Gemini Live 原声仍可作为独立调试 provider，但不再提供或展示伪童声 profile。

## 7. 回调安全

Gemini 回调与调试 API 使用不同鉴权边界：

- 每次服务启动生成一个 256-bit 随机 Bearer Token；
- Token 只写入该 RTC 任务的 `LLMConfig.APIKey`，不进入前端、数据库或 manifest；
- 回调端点使用常量时间比较验证 Token；
- Gemini API Key 只用于 Ling 后端到 Google 的请求，不会发给火山；
- 传给 Gemini 的请求体采用字段白名单，丢弃火山自定义数据和业务 trace；
- 服务重启后旧 Token 立即失效，旧 RTC 任务也不能继续调用新进程。

## 8. 已知边界

- 级联链路延迟高于 Gemini Live 原生音频；应继续测量首音频帧，而不只测字幕。
- Gemini 文本模型无法直接获得原生音频模型全部的语气理解信息；当前依赖 ASR 文本和视频帧。
- `seed-tts-2.0` 仍是生成模型，极端文本下可能出现演绎波动；生产前需要目标玩偶扬声器上的 20 轮长聊验收。
- ESP32 不能直接使用 ByteRTC Web SDK。硬件端需要 RTC 原生 SDK、网关或独立设备协议。
- profile 是公版合成声，不代表真实儿童身份，也不得用于冒充某个真人。

## 9. 复制音色边界

真正的参考录音复制仍保持实验状态。未来若继续，必须使用同一位成年声音提供者的合法参考录音和授权录音，并满足撤销、删除、加密存储和最小权限要求。以下内容始终禁止：

- 录制或复制儿童用户的声音作为玩偶默认声；
- 复制名人、动画角色、游戏角色或无权使用的第三方 voice；
- 伪造授权录音或授权签名；
- 将参考录音、签名或生物特征数据提交到 Git、日志或前端存储。

## 10. 官方依据

- [Gemini Live API capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities)
- [Gemini OpenAI compatibility](https://ai.google.dev/gemini-api/docs/openai)
- [火山引擎 StartVoiceChat](https://www.volcengine.com/docs/6348/1558163)
- [火山引擎接入第三方大模型或 Agent](https://www.volcengine.com/docs/6348/1399966)
- [豆包语音合成大模型双向流 API](https://www.volcengine.com/docs/6561/1329505)
