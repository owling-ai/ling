# Ling 定制音色可行性与实施方案

> 调研日期：2026-07-11
>
> 分支：`feat/custom-voice`
>
> Worktree：`/Users/liaoxingyi/workspace/ling-custom-voice`

## 1. 结论

**能做，角色音色预设已经实现；复制音色继续保持实验状态。**

1. **Gemini 角色音色预设：已实现。** 从 Gemini Live 支持的 30 个预置 voice 中选出 4 个适合儿童陪伴的底声，为每个 voice 固定角色化语气、节奏和表达约束，并用当前 Live 模型预生成同一句中文试听。用户选中的 profile 在建立 Live 会话时写入 `speechConfig`。这条路线保留当前音频到音频、低延迟、可打断和视频理解能力。
2. **参考录音复制音色：协议可用，但暂列实验功能。** Google GenAI SDK 已公开 `replicatedVoiceConfig`、参考 WAV、授权 WAV 和授权签名字段；当前项目的 Gemini API Key 实测也能让 `gemini-3.1-flash-live-preview` 接受该配置并输出音频。不过 Gemini 产品文档尚未正式说明支持范围，且还没有使用合法真人样本验证相似度、中文表现和授权签名，因此不能直接作为默认生产能力。

不建议首发时把 Google Cloud Text-to-Speech Instant Custom Voice 接到实时主链路。它能真正创建复制音色，但当前仅向 allowlist 用户开放，而且会迫使现有 Gemini 原生音频链路改成 ASR、文本模型、TTS 的级联架构，明显增加延迟、打断控制和故障面。

## 2. 当前项目基础

现有 Gemini Live 链路已经具备音色选择能力：

```json
{
  "generationConfig": {
    "responseModalities": ["AUDIO"],
    "speechConfig": {
      "voiceConfig": {
        "prebuiltVoiceConfig": {"voiceName": "Aoede"}
      }
    }
  }
}
```

当前实现位于 `backend/realtime.py`、`frontend/assets/app.js` 和 `frontend/assets/voices/`：

- 服务端公开并允许前端选择 `cloudlet`、`starlight`、`moonlamp`、`honeydrop` 四个 profile ID；`legacy` 只用于服务端兼容旧配置；
- 每个 profile 固定映射到底声、风格 instruction 和试听 URL；
- 旧调试台支持单选、试听和本地保存，建连时传 `voice_profile`；
- 未传或非法 ID 自动回退到默认 `cloudlet`；
- `LING_GEMINI_VOICE_PROFILE` 可改服务端默认，`LING_GEMINI_VOICE` 只保留给 `legacy` 兼容模式；
- 参考音频、授权音频和授权签名尚未进入产品链路。

## 3. 首发角色音色预设

Gemini 官方说明 Live 原生音频模型可以使用 Gemini TTS 的 30 个预置 voice。当前提供四个差异足够明显、不过度模仿幼儿的角色方向：

| Profile | Gemini voice | 听感方向 | 固定表达约束 |
|---|---|---|---|
| 小云朵 | `Leda` | 清亮、年轻、童真 | 自然轻软，语速略慢，句尾轻收，不夹嗓、不装婴儿 |
| 小星星 | `Achird` | 亲切、好奇、活泼 | 带微笑感，反应灵动，兴奋度受控，避免持续高音量 |
| 月亮灯 | `Vindemiatrix` | 温柔、安定、陪伴感 | 近距离讲故事感，停顿自然，不耳语，不拖长尾音 |
| 蜂蜜糖 | `Sulafat` | 温暖、圆润、安心 | 温暖但不成熟说教，节奏舒展，情绪变化柔和 |

备选 voice：`Laomedeia`（更活泼）、`Puck`（更外向）、`Achernar`（更柔软）、`Callirrhoe`（更松弛）。

这里的“预制”包含两部分：

- 预制稳定的 profile 配置：底声、角色 prompt、显示名和回退 voice；
- 预生成试听 WAV：四个 profile 使用同一段 8 至 12 秒中文台词，通过实际的 `gemini-3.1-flash-live-preview` 链路生成，避免用另一套 TTS 做出与真实通话不一致的试听。

建议试听文案同时覆盖问候、情绪和中英混说：

> 嗨，我是灵灵。今天见到你真开心！你想先聊小风筝，还是一起说 butterfly？

### 预设方案的能力边界

- voice 名称能稳定选择基础声线。
- system instruction 能约束说话习惯，但 Gemini 3.1 Live 没有公开独立的音高、语速、气息等数值控制项，细节存在回合间波动。
- Gemini TTS 的自然语言 style、accent、pace、tone 控制是官方明确能力，但 TTS 不是当前实时 Live 主链路。不能把 TTS 的精细可控程度直接等同于 Live。
- `gemini-3.1-flash-live-preview` 不支持 affective dialog，因此不能依赖它自动随孩子语气改变声线；角色音色应由固定 profile 保持一致。

## 4. Gemini 参考录音复制音色

### 4.1 SDK 暴露的协议

截至 2026-07-11，Google GenAI Python `2.11.0` 和 JavaScript `2.11.0` SDK 都包含以下配置：

```json
{
  "replicatedVoiceConfig": {
    "mimeType": "audio/wav",
    "voiceSampleAudio": "<base64>",
    "consentAudio": "<base64>"
  }
}
```

字段要求来自官方 SDK 类型：

- `audio/wav`；
- 16-bit signed little-endian；
- 24 kHz；
- `voiceSampleAudio` 是参考音色；
- `consentAudio` 是声音所有者的授权录音；
- 首次验证成功后，`setupComplete.voiceConsentSignature` 可在后续会话替代授权 WAV，以降低建连延迟；
- SDK 明确提示授权签名可能过期，失效时请求会失败。

Python SDK 从 2025-12 的 `1.54.0` 起加入 `ReplicatedVoiceConfig`，2026-03 的 `1.69.0` 起加入授权录音、授权签名和 Live setup response；JavaScript SDK 在 2025-12 的 `1.32.0` 加入复制音色，并在 2026-07 的 `2.11.0` 补齐授权签名类型。

### 4.2 当前账号协议探测

使用项目现有 API Key 对 `gemini-3.1-flash-live-preview` 做了最短建连和一句话生成探测，没有记录或提交任何真人声音：

| 探测 | 结果 |
|---|---|
| `v1beta` + `Aoede` | setup 成功，正常生成“你好” |
| `v1alpha` + `Aoede` | setup 成功 |
| 无效预置 voice | WebSocket 以 1007 拒绝，提示找不到 voice |
| 未知 voiceConfig 字段 | WebSocket 以 1007 拒绝，提示 unknown field |
| `replicatedVoiceConfig` + 合规格式的静音 WAV | setup 成功，正常生成“你好”音频 |

这证明当前 Live 服务端确实识别 `replicatedVoiceConfig`，不是简单忽略任意未知字段。但静音 WAV 不能证明音色复制质量，也没有得到授权签名；仍需声音所有者提供合法样本后才能完成端到端验收。

当前账号的 `models.list` 不会列出 SDK 测试中曾出现的内部 voice-replication 专用模型，Gemini 产品文档也没有公开复制音色章节。因此该能力应视为 **未正式文档化的实验接口**，必须带 feature flag 和预置 voice 回退，不能形成单点依赖。

### 4.3 最小合法验证素材

要完成实验，需要同一个成年声音提供者录制两段素材：

1. 一段约 8 至 10 秒、自然且有轻微情绪变化的普通话参考音频；
2. 一段按 Google 要求文本录制的授权声明。

实现前必须向 Google 确认 Gemini replicated voice 要求的准确授权文案；不能直接假设它与 Cloud TTS 的文案完全相同。不得伪造授权录音，也不建议复制儿童用户的声音。Ling 的“童真”应优先来自成年配音者或具有明确商用和合成授权的声音资产。

## 5. Cloud TTS Instant Custom Voice 备选

Google Cloud Text-to-Speech 的 Chirp 3 Instant Custom Voice 是公开文档化的真正复制音色方案：

- 支持中文 `cmn-CN`；
- 参考音频和授权音频各最长 10 秒，建议尽量接近 10 秒；
- 支持流式 LINEAR16/PCM 和批量输出；
- 生成 client-side voice cloning key，可并发复用；
- 支持 0.25x 至 2x 语速控制；
- 截至 2026-07-07，仍仅向 allowlist 用户开放，需要联系 Google Cloud 销售申请。

它不能直接替换当前 Live setup 中的 voice。当前 Gemini 3.1 Live 原生音频模型只支持 AUDIO response modality，页面看到的 output transcription 是对已生成声音的附带识别，不是可以提前交给外部 TTS 的原始台词。因此接 Cloud TTS 需要重建为：

```text
麦克风 -> 流式 ASR -> Gemini 文本模型 -> 流式 Cloud TTS -> 播放
```

这会失去或重做原生音频模型的语气理解、全双工打断、输出转写对齐和一部分视频实时语义。除非 Gemini replicated voice 最终不可用且产品强依赖声音复制，否则不应优先走这条路线。

## 6. 实施顺序

### 阶段 A：角色音色预设，已完成

1. 服务端 profile registry 已包含 `id`、显示名、Gemini voice、角色语气约束和试听 URL。
2. `_gemini_setup(pack, voice_profile)` 只接受 allowlist ID，禁止前端透传任意上游字段。
3. 受保护的旧调试台已提供四个音色的试听和单选；通话中锁定选择。
4. 四段试听已由实际 Live 模型生成，manifest 记录模型、日期、转写、时长和 SHA-256。
5. 非法 profile 回退到默认 `Leda`。
6. setup payload、非法 profile、默认回退、provider info、WebSocket 参数和 WAV 静态服务均有测试覆盖。

仍需在目标玩偶扬声器上验收长短句一致性、打断尾音和连续 10 轮的角色稳定性。

### 阶段 B：复制音色实验，需要授权录音

1. 增加 `LING_GEMINI_VOICE_MODE=replicated` feature flag，默认关闭。
2. 仅从后端私有存储读取参考 WAV、授权 WAV和授权签名，绝不提交 Git 或下发浏览器。
3. 启动时验证 WAV 的声道、位深、采样率、时长和大小。
4. 首次获得授权签名后加密保存；签名失效时重新提交授权 WAV。
5. setup 或生成失败时自动回退到已选预置 profile，不能让通话不可用。
6. 对比预置 profile 与复制音色的首包延迟、相似度、中文自然度、中英切换和 20 轮稳定性。

只有在合法真人样本实测通过、Google 确认可用范围后，才把复制音色从实验开关升级为产品能力。

## 7. 数据与合规要求

声音样本、授权录音和授权签名都按敏感生物特征数据处理：

- 不进入 Git、日志、分析事件或前端 localStorage；
- 原型期使用权限为 `0600` 的服务端文件，生产期使用加密对象存储和最小权限；
- 明确记录声音所有者、用途、授权版本、创建时间和删除状态；
- 提供撤销和彻底删除流程；
- 不允许用户上传第三方名人、儿童或无法证明权利来源的声音；
- 试听素材不得包含真实孩子姓名或任何个人信息。

## 8. 最终建议

阶段 A 已交付“小云朵 / 小星星 / 月亮灯 / 蜂蜜糖”四个可试听 profile，默认使用“小云朵”。它以较低风险改善现有音色，并完整保留 Gemini Live 的交互体验。

阶段 B 仍需等一组成年声音提供者的合法参考和授权录音后才能启用。Google Cloud TTS 只保留为复制音色无法稳定使用时的后备路线。

## 9. 官方依据

- [Gemini Live API capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities)
- [Gemini speech generation and 30 voice options](https://ai.google.dev/gemini-api/docs/speech-generation)
- [Gemini 3.1 Flash Live Preview](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-live-preview)
- [Google GenAI JavaScript SDK types](https://github.com/googleapis/js-genai/blob/main/src/types.ts)
- [Google GenAI JavaScript SDK changelog](https://github.com/googleapis/js-genai/blob/main/CHANGELOG.md)
- [Google GenAI Python SDK changelog](https://github.com/googleapis/python-genai/blob/main/CHANGELOG.md)
- [Chirp 3 Instant Custom Voice](https://cloud.google.com/text-to-speech/docs/chirp3-instant-custom-voice)
