"""对话引擎（热路径）。

- 开场：一次 DB 读组装记忆包 → 预生成开场白（记忆钩子），零 LLM。
- 回合：有 API key 走 claude；没有走规则引擎（mock）。两条路共用同一个
  「编织追踪器」：曝光/识别/产出、分享事件、互动拍、撤退规则，全部在这里记账，
  所以 demo 的学习闭环不依赖任何云端服务。
"""
import json
import random
import re
import uuid

from . import db, life, llm, memory, prompts

SESSIONS: dict[str, dict] = {}

RETREAT_WORDS = ["不想", "无聊", "别说英语", "不要英语", "烦", "不学", "别教"]
POSITIVE_ACKS = ["好", "哇", "喜欢", "真", "酷", "棒", "想", "嗯"]


# ---------------------------------------------------------------- 会话生命周期

def start_session(child_id: int) -> dict:
    pack = memory.build_memory_pack(child_id)
    session_id = uuid.uuid4().hex[:12]
    child_name = pack["child_card"].get("name", "小朋友")
    hook = pack.get("memory_hook") or ""
    opening = f"{child_name}！你来啦！{hook}" if hook else f"{child_name}！你来啦！今天过得怎么样呀？"

    sid = db.execute(
        "INSERT INTO sessions(child_id,started_at,transcript_json) VALUES(?,?,?)",
        (child_id, db.now(), json.dumps([{"role": "assistant", "content": opening}], ensure_ascii=False)),
    )
    SESSIONS[session_id] = {
        "db_id": sid,
        "child_id": child_id,
        "pack": pack,
        "history": [{"role": "assistant", "content": opening}],
        "woven": [],            # 玩偶已带出的目标词
        "shared": False,        # 待分享事件是否已经分享
        "pending_choice": False,  # 互动拍已抛出，等孩子的决定
        "retreated": False,     # 撤退规则已触发，今天不再复习
        "canon_written": [],
        "turn": 0,
    }
    db.execute("UPDATE session_agenda SET status='consumed' WHERE child_id=? AND date=?",
               (child_id, db.today()))
    return {"session_id": session_id, "opening": opening, "memory_pack": pack}


def handle_message(session_id: str, text: str, image_b64: str | None = None) -> dict:
    s = SESSIONS.get(session_id)
    if not s:
        raise KeyError("session not found")
    s["turn"] += 1
    _track_child_message(s, text)
    s["history"].append({"role": "user", "content": text})

    reply = None
    if llm.live_mode():
        reply = llm.chat(prompts.build_doll_system(s["pack"]), s["history"],
                         image_b64=image_b64 if llm.supports_vision() else None)
    if not reply:
        reply = _mock_reply(s, text, has_image=bool(image_b64))

    _track_doll_reply(s, reply)
    s["history"].append({"role": "assistant", "content": reply})
    db.execute("UPDATE sessions SET transcript_json=? WHERE id=?",
               (json.dumps(s["history"], ensure_ascii=False), s["db_id"]))
    return {
        "reply": reply,
        "woven": list(s["woven"]),
        "shared": s["shared"],
        "pending_choice": s["pending_choice"],
        "retreated": s["retreated"],
        "canon_written": s["canon_written"],
    }


def get_session(session_id: str):
    return SESSIONS.get(session_id)


# ---------------------------------------------------------------- 编织追踪器（两种模式共用）

def _review_words(s):
    return [r for r in s["pack"].get("review_items", []) if r.get("type") == "word"]


def _track_doll_reply(s, reply: str):
    for r in _review_words(s):
        if re.search(rf'\b{re.escape(r["word"])}\b', reply, re.I) and r["word"] not in s["woven"]:
            s["woven"].append(r["word"])
    ev = s["pack"].get("share_event")
    if ev and not s["shared"]:
        overlap = any(v.lower() in reply.lower() for v in ev.get("vocab", [])) or ev["text"][:8] in reply
        if overlap:
            s["shared"] = True
            db.execute("UPDATE doll_events SET share_status='shared' WHERE id=?", (ev["id"],))
    q = s["pack"].get("interactive_question") or ""
    if (s["shared"] and q and not s.get("choice_done")
            and (q[:6] in reply or ("怎么办" in reply and "？" in reply))):
        s["pending_choice"] = True


def _track_child_message(s, text: str):
    child_id = s["child_id"]
    # 撤退规则：孩子明显没兴趣 → 立刻放下复习
    if any(w in text for w in RETREAT_WORDS):
        s["retreated"] = True
    # 记忆钩子被接住：孩子第一句回答了钩子里的悬念（如起名字）→ 直接落成事实
    hook = s["pack"].get("memory_hook") or ""
    if s["turn"] == 1 and ("名字" in hook or "叫" in hook):
        m = re.search(r"叫([一-鿿A-Za-z]{1,8})", text)
        if m:
            s["hook_answer"] = m.group(1).strip()
            memory.add_fact(child_id, f"给三角龙玩具起名叫「{s['hook_answer']}」", "interest",
                            "dinosaur-name", 0.9, "session:hook")
    # 产出：孩子自己说出英文目标词
    for r in _review_words(s):
        if re.search(rf'\b{re.escape(r["word"])}\b', text, re.I):
            life.record_mastery(child_id, r["item_id"], "produced")
            if r["word"] not in s["woven"]:
                s["woven"].append(r["word"])
    # 识别：玩偶带出过的词，孩子用中文意思/积极回应接住
    for r in _review_words(s):
        if r["word"] in s["woven"] and (r["zh"] in text or any(a in text for a in POSITIVE_ACKS)):
            life.record_mastery(child_id, r["item_id"], "recognized")
    # 互动拍：孩子的决定写进正典，成为既定事实（情绪表达不算决定）
    emo = any(w in text for w in ["难过", "哭", "生气", "害怕", "不开心"])
    if s["pending_choice"] and len(text.strip()) >= 2 and not emo \
            and not any(w in text for w in RETREAT_WORDS):
        s["choice_done"] = True
        ev = s["pack"].get("share_event") or {}
        entity = _guess_entity(s)
        canon_text = f"{s['pack']['child_card'].get('name','孩子')}决定：{text.strip()[:40]}"
        life.add_canon(child_id, entity, canon_text, by_child=True)
        if ev.get("id"):
            db.execute("UPDATE doll_events SET child_reaction=? WHERE id=?", (text.strip()[:60], ev["id"]))
        s["canon_written"].append({"entity": entity, "fact_text": canon_text})
        s["pending_choice"] = False


def _guess_entity(s):
    ev = s["pack"].get("share_event") or {}
    canon = s["pack"].get("canon") or []
    for line in canon:
        entity = line.split("：")[0]
        if entity and entity in (ev.get("text") or ""):
            return entity
    return "我们的故事"


# ---------------------------------------------------------------- 规则引擎（无 API key 兜底）

TOPIC_REPLIES = {
    "恐龙": ["三角龙有三只角，比我的耳朵还神气！你最喜欢它哪一点呀？",
             "要是三角龙来橡树村，我一定请它荡我们的蓝秋千！"],
    "画画": ["你上次画的画我还记得呢！这次画了什么呀？",
             "下次画一张橡树村好不好？我把村子的样子讲给你听。"],
    "学校": ["学校里今天有什么好玩的事吗？我特别想听。"],
    "朵朵": ["朵朵最近好吗？上次你说你们一起跳皮筋来着。"],
}


def _pick(s, options: list[str]) -> str:
    """随机挑一句，但避免和上一句逐字重复。"""
    last = s.get("last_reply", "")
    pool = [o for o in options if o != last] or options
    reply = random.choice(pool)
    s["last_reply"] = reply
    return reply


def _mock_reply(s, text: str, has_image: bool = False) -> str:
    pack = s["pack"]
    child_name = pack["child_card"].get("name", "你")

    # 孩子给玩偶看东西（摄像头帧）：离线引擎看不见，诚实但好奇地接住
    if has_image:
        return _pick(s, [
            f"哇，{child_name}给我看的这个我盯了好久！快跟我讲讲它是什么呀？",
            "让我凑近一点看看……你最喜欢它哪里呀？",
        ])

    # 刚写完正典 → 郑重感谢，孩子的选择成为既定事实
    if s["canon_written"] and s["canon_written"][-1].get("_fresh", True):
        s["canon_written"][-1]["_fresh"] = False
        c = s["canon_written"][-1]
        return f"就这么定啦！{c['fact_text'].split('：',1)[1]}——我这就记进村子的大事本里，以后这就是我们的故事啦，谢谢你帮我拿主意！"

    # 记忆钩子被接住 → 郑重回应，让"它记得我"落地
    if s.get("hook_answer") and not s.get("hook_acked"):
        s["hook_acked"] = True
        return (f"{s['hook_answer']}！这名字也太帅了吧！我这就记进小本本：{child_name}的三角龙叫"
                f"{s['hook_answer']}。下次它可以来橡树村玩，我带它荡蓝秋千！")

    # 孩子主动说出英文目标词 → 使劲夸（产出是最高层级）
    said = [r for r in _review_words(s)
            if re.search(rf'\b{re.escape(r["word"])}\b', text, re.I)]
    if said and not s["retreated"]:
        r0 = said[0]
        return (f"哇——你自己说出 {r0['word']} 了！{r0['zh']}听到都要开心坏啦。"
                f"你说英语的样子，比松鼠先生数橡果还神气！")

    # 情绪接住（优先级高于一切复习/分享）
    if any(w in text for w in ["难过", "哭", "生气", "害怕", "不开心", "批评"]):
        return _pick(s, [
            f"过来，抱一下。{child_name}愿意跟我说说发生什么了吗？说出来会好受一点，也可以找妈妈聊聊哦。",
            "我在呢，我哪儿也不去。你慢慢说，说多久我都听着。",
            f"这种时候最需要抱抱了。等会儿要不要跟妈妈也说说？她肯定也想第一时间抱住{child_name}。",
        ])

    # 撤退规则：立刻放下复习，只在触发那一刻回应一次，之后纯陪伴
    if s["retreated"] and not s.get("retreat_acked"):
        s["retreat_acked"] = True
        interests = pack["child_card"].get("interests", [])
        topic = interests[0] if interests else "好玩的事"
        return f"好呀好呀，那我们不说这个啦。我就想听你说说话——今天有没有遇到什么关于{topic}的事呀？"

    # 话题关键词
    for k, replies in TOPIC_REPLIES.items():
        if k in text:
            return _pick(s, replies)

    # 分享今天的生活事件（复习以"分享我的一天"的形态发生；撤退后不再分享带英语的事件）
    ev = pack.get("share_event")
    if ev and not s["shared"] and not s["retreated"] \
            and (s["turn"] >= 2 or any(k in text for k in ["你今天", "你呢", "你的", "你干嘛", "你做了"])):
        q = pack.get("interactive_question") or ""
        return f"跟你说个事！{ev['text']} {q}"

    # 机会主义编织：孩子聊到相关话题，顺势带词（密度上限 3；撤退后停止）
    if len(s["woven"]) < 3 and not s["retreated"]:
        for r in _review_words(s):
            if r["word"] not in s["woven"] and r["zh"] and r["zh"] in text:
                return f"对了对了！{r['zh']}用英语说是 {r['word']} 哦，我今天刚跟松鼠先生学的。你觉得{r['zh']}可爱吗？"

    # 孩子讲自己的一天 → 好奇追问
    if any(k in text for k in ["今天", "我们", "老师", "妈妈", "爸爸"]):
        return _pick(s, [
            "然后呢然后呢？我想听最好玩的那段！",
            f"哇，{child_name}的一天比我的橡果还满！那你最开心的是哪一件呀？",
            "听起来好热闹呀，要是我也在就好了。后来怎么样了？",
        ])

    # 兜底：温暖 + 从孩子卡的兴趣里找话头
    interests = pack["child_card"].get("interests", [])
    topic = random.choice(interests) if interests else "今天的事"
    return _pick(s, [
        f"嗯嗯，我在认真听呢。对了，最近{topic}怎么样啦？",
        "你说的我记住啦，会写进我的小本本里。再多讲一点嘛！",
        f"哈哈，跟{child_name}聊天是我一天里最好玩的事。还有呢还有呢？",
    ])
