# 灵 Ling · 共同成长的玩偶

> 儿童/家庭场景里的共同成长型实体 agent。孩子在长大，它也在长大。

黑客松全套可运行 demo：**没有硬件也能完整演示** —— 网页就是玩偶（浏览器语音识别当麦克风、TTS 当喇叭），**没有 API key 也能完整演示** —— 内置规则引擎兜底，五层记忆、教材编织、数字生命全流程照跑。

## 快速开始（uv 管理环境）

```bash
./run.sh            # uv sync + 启动，首次启动自动预埋一周演示数据
# 打开 http://localhost:8000
```

## 模型接入（三级自动降级，demo 永远不会挂）

按优先级自动选择，也可用 `LING_PROVIDER=openai|anthropic|mock` 强制指定：

**1️⃣ OpenAI 兼容端点（推荐）** —— 设 `LING_OPENAI_BASE_URL` 即启用，本地和第三方都行。

本地全模态 MiniCPM-o 4.5，用 [vLLM-omni](https://docs.vllm.ai/projects/vllm-omni/) 起服务：

```bash
# GPU 机器上（模型 9B：SigLip2 + Whisper + CosyVoice2 + Qwen3-8B 底座）
uv tool run --from vllm vllm serve openbmb/MiniCPM-o-4_5 --trust-remote-code --port 8001

# 灵这边只要指过去：
export LING_OPENAI_BASE_URL=http://localhost:8001/v1
export LING_OPENAI_MODEL=openbmb/MiniCPM-o-4_5   # 默认值，可省
./run.sh
```

OpenRouter / DeepSeek 等第三方托管同理：

```bash
export LING_OPENAI_BASE_URL=https://openrouter.ai/api/v1
export LING_OPENAI_API_KEY=sk-or-...
export LING_OPENAI_MODEL=deepseek/deepseek-chat
```

全模态模型（模型名含 minicpm-o / omni / vl / vision 等）自动开启聊天页的 📷 按钮——
孩子把玩具举到摄像头前，玩偶真的能看见（视频帧理解）；DeepSeek 这类纯文本模型自动
关闭，`LING_OPENAI_VISION=1/0` 可强制覆盖。

**2️⃣ Claude** —— `export ANTHROPIC_API_KEY=sk-ant-...`（对话 `LING_CHAT_MODEL` 默认
claude-opus-4-8，冷路径 `LING_WORKER_MODEL` 默认 claude-haiku-4-5）。

**3️⃣ 规则引擎** —— 什么都不配就用它：零依赖零网络，五层记忆、教材编织、
撤退规则、正典写回全流程照跑，纯软件兜底。

### 全双工路线（硬件阶段的升级）

MiniCPM-o 4.5 真正的全双工形态（连续音视频流、边听边说互不阻塞）走 OpenBMB 官方
[MiniCPM-o-Demo](https://github.com/OpenBMB/MiniCPM-o-Demo) 的 WebSocket 网关
（Gateway :8006 + GPU worker 池，Docker Compose 一键起）。届时本项目的会话服务
挂到网关的 duplex 会话上：**开场记忆包照旧注入 system prompt，转写照旧落盘走冷路径**
——记忆系统对上层是语音回合制还是全双工流式完全无感，这正是热/冷路径分离换来的。

## 三幕演示脚本

1. **开场无提示回忆**：打开「和灵灵聊天」，玩偶主动说「昨天你说要给那只三角龙起名字，起好了吗？」——实现它靠的不是高级检索，是夜间规划器预生成的记忆钩子。
2. **复习藏在生活里 + 孩子写正典**：问「你今天做了什么呀？」，玩偶分享去动物园送请柬（zoo / panda / monkey / funny 自然出现在它的生活事件里），然后请孩子帮它决定生日蛋糕口味——孩子的决定写进世界正典，成为既定事实。
3. **家长看到成长**：结束会话看冷路径产出（日记 / 新事实 / 掌握度回写），家长控制台里有成长曲线、「主动说出 N 个新词」（付费按钮）、被作废的旧事实（以前怕黑 → 现在不怕了）、玩偶视角的日记。

加分项：说「我不想说英语」触发**撤退规则**（玩偶和点读机的分界线）；「灵灵的世界」里点生活时钟，看它孩子不在时也在生活。

## 架构

```
┌─ 热路径（实时，禁止 LLM 记忆调用）────────────────────┐
│ 网页玩偶(ASR/TTS/📷) → 会话服务 → MiniCPM-o/Claude/规则引擎 │
│        ↑ 开场一次性预取「记忆包」（纯 DB 读，<50ms）      │
└──────────────────────┬──────────────────────────────┘
                       │ 转写落盘
┌─ 冷路径（异步）───────▼──────────────────────────────┐
│ 记忆工人：写日记(L2) / 抽事实(L3) / SRS 掌握度回写        │
│ 夜间规划器：挑到期词 + 记忆钩子 → 今日议程               │
│ 生活时钟：推进故事弧，复习词织进玩偶明天的生活事件         │
│ 反思引擎：7 天日记 → 成长快照(L4) + 玩偶视角日记          │
└─────────────────────────────────────────────────────┘
三个客户端共用同一记忆服务：网页玩偶 / 线上分身 / 家长控制台
```

### 五层记忆

| 层 | 表 | 作用 |
|---|---|---|
| L0 工作记忆 | 进程内 | 最近 N 轮对话 |
| L1 核心卡片 | `core_cards` | 孩子卡 + 玩偶状态卡，常驻 prompt，性格稳定性的锚 |
| L2 情景日记 | `diary_entries` | append-only，一日一叶 / 家长报告 / 记忆钩子全从这出 |
| L3 事实记忆 | `facts` | `valid_from / superseded_by` —— 成长感藏在被作废的旧事实里 |
| L4 反思成长 | `growth_snapshots` | 兴趣趋势、里程碑、玩偶视角日记 |

### 教材复习闭环（英语学习不惹人烦的关键）

玩偶的"自己的生活"就是复习内容的运载工具：夜间规划器从 SRS-lite 掌握度表挑 3-5 个到期项 → 生活时钟把目标词织进玩偶明天的生活事件 → 热路径开场注入议程（密度上限 3 / 机会主义触发 / **撤退规则**）→ 会话后提取器判定 曝光→识别→产出 三层并回写间隔。

### 数字生命

孩子的 L1-L4 原封不动给玩偶自己再跑一份，再加三样：**世界正典 Canon**（设定账本，防三天自相矛盾）、**故事弧引擎**（5 拍骨架 + 生成）、**生活时钟**（每天都跑，不管孩子来没来）。互动拍把故事难题抛给孩子，孩子的选择写回正典——"一起写故事"的落地形态。

## 代码结构

```
backend/
  app.py       FastAPI 路由（记忆服务 API + 静态前端）
  db.py        SQLite schema（全部表）
  memory.py    L1-L4 读写 + 热路径记忆包组装
  engine.py    对话引擎：编织追踪器 + 规则引擎兜底
  llm.py       Anthropic 接入，失败/无 key 自动降级
  prompts.py   全部 prompt 模板
  workers.py   冷路径：日记/事实/掌握度/反思
  life.py      夜间规划器 / 生活时钟 / 故事弧 / SRS
  seed.py      预埋一周演示数据
  curriculum/  课程包 JSON（人教 PEP 三上）
frontend/      无构建步骤的单页应用（现场断网也能跑）
```
