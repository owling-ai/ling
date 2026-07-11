# 灵 Ling · 共同成长的玩偶

> 儿童/家庭场景里的共同成长型实体 agent。孩子在长大，它也在长大。

黑客松全套可运行 demo：**没有硬件也能完整演示** —— 网页就是玩偶，接通就直接说话、随时打断（Gemini Live / StepFun / 火山引擎 RTC，可在前端切换）。记忆系统（五层记忆、教材编织、数字生命）与语音链路解耦：**冷路径没有任何 API key 也照跑**，内置规则抽取器兜底。

## 黑客松 Demo 入口

一条命令启动后端、旧玩偶控制台、儿童端、家长端和本地 mock 图片/视频素材：

```bash
./run.sh
```

`run.sh` 默认使用 `LING_PROVIDER=mock`，即使本机 `.env` 里有真实 worker key，黑客松演示的会话结束与生成链路也不会被外部模型调用拖住；需要验证真实冷路径时再显式 `LING_PROVIDER=openai ./run.sh` 或 `LING_PROVIDER=anthropic ./run.sh`。

打开这些入口：

- `http://localhost:8888/`：旧网页玩偶/调试控制台，保留实时语音和记忆调试能力。
- `http://localhost:8888/child/`：儿童端「灵灵的窗口」，手机优先 PWA，展示全局基础世界、孩子私有瞬间和信物口袋。
- `http://localhost:8888/parent/`：家长端「训练师手册」，手机优先 PWA，只读取受控家长投影。
- `http://localhost:8888/design`：已批准的积木 + 夜灯昼夜视觉稿。

本轮黑客松不现场调用 Seedance/Veo。后端用 `MockMediaProvider` 模拟“提交生成 -> 渲染中 -> 发布”的状态机，实际展示读取 `backend/demo_media/` 下预生成的本地 MP4/PNG。彩排时可触发一个专属瞬间：

```bash
curl -X POST http://localhost:8888/api/admin/demo-moment \
  -H 'Content-Type: application/json' \
  -d '{"event_key":"canon_choice","event_value":"橡果味","source_id":"demo-1"}'
```

随后儿童端 feed 会先出现 `rendering`，约 2-4 秒后 `/api/moments/{id}` 发布本地视频与信物；收藏状态通过 `/api/pocket/{keepsake_id}` 持久化。

服务默认只监听 `127.0.0.1`。管理接口和旧调试控制台的原始记忆接口只允许本机访问；显式改为对外监听时，需设置 `LING_ADMIN_TOKEN` 并通过 `Authorization: Bearer <token>` 访问这些接口。儿童端和家长端只使用受控投影，不需要管理令牌。

常用验证命令：

```bash
.venv/bin/python -m pytest -q
node --test frontend/child/tests/*.test.mjs
node --test frontend/parent/tests/*.test.mjs
.venv/bin/python -m compileall -q backend tests
```

明确延期到生产阶段的事项：真实 Seedance/Veo 接入、队列/对象存储/CMS、生产 ACL、多孩多账号、通知投递、完整账户注销销毁流程，以及家长端写入型设置。

## 当前产品设计与开发进展

「灵」现在是一只以实体玩偶为核心、由两个独立手机端共同承接体验的成长伙伴。黑客松阶段，孩子端和家长端都实现为可安装、手机优先的 PWA；后续是否封装为原生 App，不改变当前产品与数据边界。

| 使用端 | 当前定位 |
|---|---|
| 实体玩偶 / 网页模拟器 | 主要互动与记忆写入入口，负责实时语音、视觉理解和孩子选择 |
| 孩子端「灵灵的窗口」 | `现在 / 奇遇 / 口袋`：看灵灵此刻的生活、共同生成的专属瞬间与收藏信物 |
| 家长端「训练师手册」 | `今日 / 成长 / 记忆 / 守护`：只读取家长可见的受控投影，不展示原始转写和内部生成数据 |

当前视觉方向已经确定为 **白天积木 + 睡前夜灯**：白天强调可触摸、可行动的积木玩具感；夜间转为靛蓝与少量暖金，像床头小夜灯。昼夜不是前端换肤，而是由后端的统一作息和时间槽决定，所有孩子看到语义一致的基础世界。

产品的数据与故事由两个事实来源和一层受控投影共同组成：

- **全局基础世界**：所有灵灵遵循一致作息与基础事件；同一事件可以为不同批次稳定分配不同镜头的视频，但不能改变事件事实。
- **孩子私有覆盖层**：L1-L4 记忆、学习掌握度、私有 Canon 和连续故事随孩子共同成长；只有有意义的互动和孩子确认的选择才推进专属故事。
- **体验投影**：专属瞬间、视频和信物来自记忆事实源，但不是新的记忆层；孩子端只写收藏状态，家长端只看允许公开的摘要、成长变化和共同信物。

目前正在推进的是黑客松 Demo 的最后收敛：继续打磨双端移动体验和离线彩排流程，扩充少量高质量预生成素材，并保持媒体生成 provider 接口可替换。现场演示始终以本地 Mock 状态机和预生成素材为主，不让真实视频 API 的耗时、费用或网络状态影响演示。

完整设计决策见 [《Ling · 记忆架构：事实源、体验投影与数字生命》](./Ling-%E8%AE%B0%E5%BF%86%E6%9E%B6%E6%9E%84%E8%AE%BE%E8%AE%A1.md)，实现拆解见 [黑客松双端实施计划](./docs/superpowers/plans/2026-07-11-hackathon-mobile-apps.md)。

## 快速开始（uv 管理环境）

```bash
export GEMINI_API_KEY=...    # Gemini Live
export STEPFUN_API_KEY=...   # 可选；配置后可在前端切换到 StepFun
# 火山引擎为第三种可选接入，所需四项凭证见下文
./run.sh                     # uv sync + 启动，首次启动自动预埋一周演示数据
# 打开 http://localhost:8888
```

## 模型接入

所有环境变量都可以写进项目根目录的 `.env`，启动时自动读取（shell 里已有的变量优先）：

```bash
cp .env.example .env   # 然后按需填写
```

### 交互内核：Gemini Live / StepFun / 火山引擎 RTC

配置任意一种后端凭证即可通话；配置多种时，聊天页可以实时切换模型。进入聊天页不会自动申请设备权限或连接模型，点击「接通」后才创建会话。默认使用支持音频与摄像头画面输入的预览模型 `gemini-3.1-flash-live-preview`；也保留 StepFun `stepaudio-2.5-realtime` 语音通道，并支持火山引擎「AI 音视频互动方案」。模型一轮说完后连续安静约 20 秒，会触发一次轻量陪伴回应；下一次至少间隔 45 秒，每场最多两次。第一次禁止带记忆和学习，第二次也只有当前话题或画面自然相关时才可带一个词。

```bash
export GEMINI_API_KEY=...
export LING_GEMINI_LIVE_MODEL=gemini-3.1-flash-live-preview
export LING_GEMINI_VOICE=Aoede

# 可选的第二提供商
export STEPFUN_API_KEY=...
export LING_STEPFUN_VOICE=linjiajiejie

# 可选：指定默认提供商和 HTTP 代理
export LING_REALTIME_PROVIDER=gemini
export HTTPS_PROXY=http://127.0.0.1:7890
```

Gemini 和 StepFun 仍通过 `/api/realtime/ws?provider=gemini|stepfun` 由后端代理。Gemini 使用 16kHz 上行与 24kHz 下行 PCM；开启摄像头后，以 1 FPS 发送最长边 512px 的 JPEG 帧。StepFun 上下行均为 24kHz PCM，当前不发送视频。API key 不会下发到前端。

火山引擎采用官方 RTC 架构：浏览器通过项目内固定的 `@volcengine/rtc@4.68.5` 加入房间并发布麦克风/摄像头，后端签发一小时 RTC Token，再以 IAM AK/SK 签名调用 `StartVoiceChat`、`UpdateVoiceChat` 和 `StopVoiceChat`。浏览器不会收到 RTC AppKey、AK 或 SK。请在火山控制台创建 **AI 音视频互动方案**应用，不要使用另一个商品「实时对话式 AI」的 AppId：

```bash
export VOLCENGINE_RTC_APP_ID=...
export VOLCENGINE_RTC_APP_KEY=...
export VOLCENGINE_ACCESS_KEY=...
export VOLCENGINE_SECRET_KEY=...
export LING_REALTIME_PROVIDER=volcengine

# 可选：按账号已开通的资源调整
export LING_VOLC_ARK_MODEL=doubao-seed-2-1-turbo-260628
export LING_VOLC_TTS_VOICE=zh_female_linjianvhai_moon_bigtts
```

火山默认使用 `doubao-seed-2-1-turbo-260628`，关闭深度思考并启用 ASR Prefill；视觉请求只携带最近一张 360p 低细节画面。还会用通话开始后的 4 秒目标语音自动建立临时声纹，并过滤其他说话人。摄像头打开后由 RTC 服务端按 1 秒间隔抽帧；正常问答会自动携带最近画面。冷场观察复用每场最多两次的预算，通过 `UpdateVoiceChat(ExternalTextToLLM, InterruptMode=2)` 检查缓存画面，不打断当前讲话。字幕按官方 `subv` 二进制协议解析，最终分句回传后端进入同一记忆闭环。实现依据为官方 [Web RTC 快速开始](https://www.volcengine.com/docs/6348/106914)、[Token 鉴权](https://www.volcengine.com/docs/6348/70121)、[StartVoiceChat](https://www.volcengine.com/docs/6348/2123348)、[视频和图片理解](https://www.volcengine.com/docs/6348/1408245) 与 [实时字幕](https://www.volcengine.com/docs/6348/2165060)。

Gemini Live 的页面文字来自同一会话返回的 `inputAudioTranscription` / `outputAudioTranscription`。原生音频模型直接生成音频 token，转写是对音频的附带识别结果，不是用于合成声音的原始文本，因此可能在用词、断句和标点上与实际听到的内容略有差异。默认通过 `languageHints` 将候选语言限制在简体中文与美式英语，并把当次课程词、角色名加入 `adaptationPhrases`，降低中英混说被误判成韩文等其他语言的概率。可用 `LING_GEMINI_TRANSCRIPTION_LANGUAGES` 覆盖语言列表。

项目使用 `websockets>=12`；当前锁定版本 16 会自动读取 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`。对于 `wss://` 上游，通常设置 `HTTPS_PROXY=http://代理地址:端口`，代理需要支持 HTTP CONNECT。

### 冷路径：记忆工人（可选，三级自动降级）

日记 / 事实抽取 / 反思 / 夜间规划走独立的文本模型，按优先级自动选择（`LING_PROVIDER=openai|anthropic|mock` 可强制）：

**1️⃣ OpenAI 兼容端点** —— 设 `LING_WORKER_BASE_URL` 即启用（SiliconFlow / OpenRouter / DeepSeek 官方 / 本地 ollama 都行）：

```bash
export LING_WORKER_BASE_URL=https://openrouter.ai/api/v1
export LING_WORKER_API_KEY=sk-or-...
export LING_WORKER_MODEL=deepseek/deepseek-chat
```

**2️⃣ Claude** —— `export ANTHROPIC_API_KEY=sk-ant-...`（模型 `LING_ANTHROPIC_WORKER_MODEL` 默认 claude-haiku-4-5）。

**3️⃣ 规则抽取器** —— 什么都不配就用它：零依赖零网络，写日记、抽事实、掌握度回写和夜间规划全流程照跑，输出结构与 LLM 版完全一致。

### 全双工路线（硬件阶段的升级）

硬件形态（连续音视频流、边听边说互不阻塞）可换 OpenBMB 官方 [MiniCPM-o-Demo](https://github.com/OpenBMB/MiniCPM-o-Demo) 的 WebSocket 网关（Gateway :8006 + GPU worker 池）。届时会话服务挂到网关的 duplex 会话上：开场记忆包照旧注入 system prompt，转写照旧落盘走冷路径——记忆系统对上层是哪家语音模型完全无感。

## 三幕演示脚本

1. **纯问候后自然回忆**：接通时玩偶只简单说「嗨，我在呢」，不提昨天、不问问题；聊过两轮后，在自然相关或冷场时才可提起「昨天那只三角龙起好名字了吗？」。关系线索由夜间规划器预生成，不做现场检索。
2. **复习藏在生活里 + 孩子写正典**：问「你今天做了什么呀？」，玩偶分享去动物园送请柬（zoo / panda / monkey / funny 自然出现在它的生活事件里），然后请孩子帮它决定生日蛋糕口味——孩子的决定写进世界正典，成为既定事实。
3. **家长看到成长**：结束通话看冷路径产出（日记 / 新事实 / 掌握度回写），家长控制台里有成长曲线、「主动说出 N 个新词」（付费按钮）、被作废的旧事实（以前怕黑 → 现在不怕了）、玩偶视角的日记。

加分项：说「我不想说英语」触发**撤退规则**（玩偶和点读机的分界线）；「灵灵的世界」里点生活时钟，预览所有孩子同步的基础世界作息。

## 架构

```
┌─ 热路径（实时，禁止 LLM 记忆调用）────────────────────────┐
│ 网页玩偶 ↔ WS 代理 ↔ Gemini / StepFun；或 ↔ ByteRTC ↔ 火山 AI │
│   开场一次性预取「记忆包」（纯 DB 读，<50ms）注入 instructions │
│   双向转写截获 → 编织追踪器记账（曝光/识别/产出、撤退、正典）   │
└──────────────────────┬───────────────────────────────┘
                       │ 转写落盘
┌─ 冷路径（异步）───────▼───────────────────────────────┐
│ 记忆工人：写日记(L2) / 抽事实(L3) / SRS 掌握度回写          │
│ 夜间规划器：挑到期词 + 记忆钩子 → 今日议程                 │
│ 基础世界时钟：按时间槽投影统一作息；私有故事只由互动推进       │
│ 反思引擎：7 天日记 → 成长快照(L4) + 玩偶视角日记            │
└───────────────────────────────────────────────────────┘
三个客户端共用同一记忆服务：网页玩偶 / 线上分身 / 家长控制台
```

### 五层记忆

| 层          | 表                 | 作用                                                       |
| ----------- | ------------------ | ---------------------------------------------------------- |
| L0 工作记忆 | 进程内             | 最近 N 轮对话                                              |
| L1 核心卡片 | `core_cards`       | 孩子卡 + 玩偶状态卡，常驻 prompt，性格稳定性的锚           |
| L2 情景日记 | `diary_entries`    | append-only，一日一叶 / 家长报告 / 记忆钩子全从这出        |
| L3 事实记忆 | `facts`            | `valid_from / superseded_by` —— 成长感藏在被作废的旧事实里 |
| L4 反思成长 | `growth_snapshots` | 兴趣趋势、里程碑、玩偶视角日记                             |

### 教材复习闭环（英语学习不惹人烦的关键）

玩偶的"自己的生活"就是复习内容的运载工具：夜间规划器从 SRS-lite 掌握度表挑 3-5 个到期项 → 下次互动时借统一基础世界或已有私有故事自然带出 → 热路径注入议程但禁止开场使用（密度上限 3 / 机会主义触发 / **撤退规则**）→ 转写记账判定 曝光→识别→产出 三层并回写间隔。

### 数字生命

数字生命由两层组成：所有孩子按同一时间槽看到**基础世界**；每个孩子再拥有自己的 Canon、故事弧和共同经历。基础世界不读私有记忆；只有确认的孩子选择或其他有意义互动才会原子地写入 Canon 并推进一拍私有故事。

## 代码结构

```
backend/
  app.py       FastAPI 路由（记忆服务 API + 静态前端）
  db.py        SQLite schema（全部表）
  memory.py    L1-L4 读写 + 热路径记忆包组装
  engine.py    会话状态 + 编织追踪器（转写记账 / 撤退规则 / 正典写回）
  realtime.py  Gemini / StepFun 实时代理（鉴权 + 协议转换 + 转写截获）
  volcengine_rtc.py  火山 RTC Token + OpenAPI 控制面 + 字幕记账
frontend/assets/
  volcengine-rtc.min.js      官方 Web SDK 4.68.5
  volcengine-rtc.LICENSE     SDK BSD-3-Clause 许可证
  llm.py       冷路径记忆工人 LLM 接入（OpenAI 兼容 / Anthropic，失败降级规则抽取器）
  prompts.py   全部 prompt 模板
  workers.py   冷路径：日记/事实/掌握度/反思
  life.py      夜间规划器 / 基础世界时钟 / 私有故事事务 / SRS
  seed.py      预埋一周演示数据
  curriculum/  课程包 JSON（人教 PEP 三上）
frontend/      无构建步骤的单页应用
```
