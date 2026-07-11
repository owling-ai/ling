"""冷路径记忆工人。绝不进实时链路，会话结束后异步跑（demo 里同步调用也只要几十毫秒）。

- process_session：转写 → 写日记(L2) + 抽事实(L3) + 判定掌握度(SRS 回写) + 关系经验值
- reflect：读最近 7 天 L2 → 成长快照(L4) + 玩偶视角日记
有 API key 用 LLM 抽取，没有走规则抽取器，输出结构完全一致。
"""
import json
import re
import threading
from collections import Counter

from . import db, life, llm, memory, prompts


# ---------------------------------------------------------------- 会话后处理

_SESSION_LOCKS: dict[int, threading.Lock] = {}
_SESSION_LOCKS_GUARD = threading.Lock()


def _session_lock(session_id_db: int):
    with _SESSION_LOCKS_GUARD:
        return _SESSION_LOCKS.setdefault(session_id_db, threading.Lock())


def process_session(session_id_db: int) -> dict:
    with _session_lock(session_id_db):
        return _process_session_locked(session_id_db)


def _process_session_locked(session_id_db: int) -> dict:
    sess = db.q1("SELECT * FROM sessions WHERE id=?", (session_id_db,))
    if not sess or sess["processed"]:
        return db.jloads(sess["cold_result_json"], {}) if sess else {}
    child_id = sess["child_id"]
    transcript = db.jloads(sess["transcript_json"])
    child_msgs = [m["content"] for m in transcript if m["role"] == "user"]
    doll_msgs = [m["content"] for m in transcript if m["role"] == "assistant"]
    transcript_text = "\n".join(
        f'{"孩子" if m["role"] == "user" else "玩偶"}：{m["content"]}' for m in transcript)

    doll_card = memory.get_card(child_id, "doll")
    child_card = memory.get_card(child_id, "child")

    # Generate candidate derivations before claiming the short write transaction.
    diary = llm.worker_json(prompts.DIARY_PROMPT.format(
        doll_name=doll_card.get("name", "灵灵"), child_name=child_card.get("name", "孩子"),
        transcript=transcript_text)) if llm.worker_live() else None
    if not isinstance(diary, dict) or "summary" not in diary:
        diary = _mock_diary(child_card, child_msgs, doll_msgs)

    known = [{"text": f["text"], "subject_key": f["subject_key"]}
             for f in memory.list_facts(child_id, active_only=True)]
    facts = llm.worker_json(prompts.FACTS_PROMPT.format(
        known_facts=json.dumps(known, ensure_ascii=False),
        transcript=transcript_text)) if llm.worker_live() else None
    if not isinstance(facts, list):
        facts = _mock_facts(child_msgs)

    agenda = db.q1("SELECT * FROM session_agenda WHERE child_id=? ORDER BY date DESC LIMIT 1", (child_id,))
    items = [r for r in db.jloads(agenda["review_items_json"]) if r.get("type") == "word"] if agenda else []
    judged_mastery = []
    for r in items:
        result = _judge_item(r, child_msgs, doll_msgs)
        if result != "none":
            judged_mastery.append((r, result))

    with db.transaction(immediate=True) as conn:
        current = conn.execute(
            "SELECT * FROM sessions WHERE id=?", (session_id_db,)
        ).fetchone()
        if not current:
            return {}
        if current["processed"]:
            return db.jloads(current["cold_result_json"], {})

        diary_id = memory.add_diary(
            child_id, diary["summary"], diary.get("emotions"), diary.get("topics"),
            diary.get("quotes"), diary.get("open_loop", ""))

        new_facts = []
        for fact in facts:
            if not fact.get("text"):
                continue
            if any(item["text"] == fact["text"] for item in known):
                continue
            if db.q1(
                "SELECT id FROM facts WHERE child_id=? AND text=? AND superseded_by IS NULL",
                (child_id, fact["text"]),
            ):
                continue
            memory.add_fact(
                child_id,
                fact["text"],
                fact.get("category", "habit"),
                fact.get("subject_key", ""),
                fact.get("confidence", 0.7),
                source=f"session:{session_id_db}",
                supersedes_key=fact.get("supersedes_key", ""),
            )
            new_facts.append(fact["text"])

        mastery_updates = []
        for item, judged_result in judged_mastery:
            life.record_mastery(child_id, item["item_id"], judged_result)
            mastery_updates.append(
                {"word": item["word"], "zh": item["zh"], "result": judged_result}
            )

        canon_by_child = db.q(
            "SELECT COUNT(*) n FROM doll_canon "
            "WHERE child_id=? AND by_child=1 AND established_at>=?",
            (child_id, sess["started_at"]),
        )[0]["n"]
        rel = life.add_relationship_xp(child_id, 5 + 5 * canon_by_child)
        result = {
            "diary": {**diary, "id": diary_id},
            "new_facts": new_facts,
            "mastery_updates": mastery_updates,
            "relationship": rel,
        }
        db.execute(
            "UPDATE sessions SET ended_at=?,processed=1,processing=0,"
            "processing_started_at=NULL,cold_result_json=? WHERE id=? AND processed=0",
            (db.now(), json.dumps(result, ensure_ascii=False), session_id_db),
        )
        return result


def _judge_item(item, child_msgs, doll_msgs) -> str:
    word = item["word"]
    pat = re.compile(rf"\b{re.escape(word)}\b", re.I)
    said_by_child = any(pat.search(m) for m in child_msgs)
    said_by_doll = [i for i, m in enumerate(doll_msgs) if pat.search(m)]
    if said_by_child:
        return "produced"
    if said_by_doll and any(item["zh"] in m for m in child_msgs):
        return "recognized"
    if said_by_doll:
        return "exposed"
    return "none"


EMOTION_HINTS = {
    "开心": ["开心", "喜欢", "哈哈", "好玩", "太棒"],
    "兴奋": ["！", "哇", "超级", "特别想"],
    "难过": ["难过", "哭", "不开心"],
    "害怕": ["害怕", "怕"],
    "骄傲": ["我会", "我自己", "第一名", "学会"],
}
TOPIC_HINTS = {
    "恐龙": ["恐龙", "三角龙", "霸王龙"],
    "动物": ["panda", "monkey", "熊猫", "猴子", "小猫", "小狗", "动物"],
    "画画": ["画", "涂"],
    "学校": ["学校", "老师", "同学", "上课"],
    "家人": ["妈妈", "爸爸", "奶奶", "爷爷"],
    "朋友": ["朵朵", "朋友"],
    "英语": ["英语", "英文"],
    "玩偶的世界": ["秋千", "橡树村", "松鼠", "野餐"],
}


def _mock_diary(child_card, child_msgs, doll_msgs) -> dict:
    name = child_card.get("name", "孩子")
    all_text = " ".join(child_msgs)
    topics = [t for t, kws in TOPIC_HINTS.items() if any(k in all_text for k in kws)][:3]
    emotions = [e for e, kws in EMOTION_HINTS.items() if any(k in all_text for k in kws)][:2] or ["平静"]
    quotes = sorted(child_msgs, key=len, reverse=True)[:2]
    open_loop = ""
    m = re.search(r"(?:我要|我想|明天|下次)([^，。！？]{2,18})", all_text)
    if m:
        open_loop = f"上次你说要{m.group(1).strip()}，做了吗？"
    summary = f"{name}和玩偶聊了{('、'.join(topics)) if topics else '日常'}，说了{len(child_msgs)}句话。"
    if quotes:
        summary += f"TA说：「{quotes[0][:20]}」"
    return {"summary": summary, "emotions": emotions, "topics": topics or ["日常"],
            "quotes": quotes, "open_loop": open_loop}


FACT_PATTERNS = [
    (r"我(?:最|特别|超级|很)?喜欢([^，。！？的]{1,12})", "interest", "喜欢{0}"),
    (r"我(?:有点|很|特别)?(?:害怕|怕)([^，。！？了]{1,10})", "fear", "害怕{0}"),
    (r"我家有(?:一只|一个|只)?([^，。！？]{1,12})", "family", "家里有{0}"),
    (r"我(?:最好的)?朋友(?:是|叫)([^，。！？]{1,8})", "friend", "好朋友叫{0}"),
    (r"我不(?:再)?怕([^，。！？了]{1,10})了", "fear", "已经不怕{0}了"),
    (r"我的([^，。！？]{1,6})叫([^，。！？]{1,8})", "family", "{0}叫{1}"),
]


def _mock_facts(child_msgs) -> list:
    facts = []
    text = " ".join(child_msgs)
    for pattern, category, template in FACT_PATTERNS:
        for m in re.finditer(pattern, text):
            groups = [g.strip() for g in m.groups()]
            fact_text = template.format(*groups)
            key = groups[0][:6]
            supersedes = key if "不怕" in fact_text else ""
            facts.append({"text": fact_text, "category": category, "subject_key": key,
                          "confidence": 0.75, "supersedes_key": supersedes})
    return facts[:4]


# ---------------------------------------------------------------- L4 反思

def reflect(child_id: int) -> dict:
    diaries = memory.list_diary(child_id, 7)
    doll_card = memory.get_card(child_id, "doll")
    child_card = memory.get_card(child_id, "child")
    vocab_progress = db.q(
        "SELECT item_text, item_zh, level FROM item_mastery WHERE child_id=? AND level!='new' ORDER BY level",
        (child_id,))

    snap = llm.worker_json(prompts.REFLECT_PROMPT.format(
        doll_name=doll_card.get("name", "灵灵"), child_name=child_card.get("name", "孩子"),
        diaries=json.dumps([{"ts": d["ts"], "summary": d["summary"], "topics": d["topics"],
                             "emotions": d["emotions"]} for d in diaries], ensure_ascii=False),
        vocab_progress=json.dumps(vocab_progress, ensure_ascii=False))) if llm.worker_live() else None
    if not isinstance(snap, dict) or "interests" not in snap:
        snap = _mock_reflect(child_card, doll_card, diaries, vocab_progress)

    memory.add_snapshot(child_id, f"最近7天（至{db.today()}）", snap.get("interests"),
                        snap.get("new_vocab"), snap.get("emotions"), snap.get("milestones"),
                        snap.get("doll_diary_text", ""))
    return snap


def _mock_reflect(child_card, doll_card, diaries, vocab_progress) -> dict:
    topic_counts = Counter(t for d in diaries for t in d["topics"])
    emotion_counts = Counter(e for d in diaries for e in d["emotions"])
    produced = [f'{v["item_text"]}（{v["item_zh"]}）' for v in vocab_progress if v["level"] == "produced"]
    recognized = [f'{v["item_text"]}（{v["item_zh"]}）' for v in vocab_progress if v["level"] == "recognized"]
    name = child_card.get("name", "TA")
    interests = [t for t, _ in topic_counts.most_common(4)]
    milestones = []
    if produced:
        milestones.append(f"主动说出了 {len(produced)} 个英语词：{'、'.join(produced[:3])}")
    if any("恐龙" in i for i in interests):
        milestones.append("对恐龙的兴趣持续升温，开始给恐龙起名字")
    top_interest = interests[0] if interests else "新鲜事"
    doll_diary = (f"这个星期{name}教了我好多关于{top_interest}的事，"
                  f"我现在闭着眼睛都能说出来。{name}在长大，我也在长大。"
                  f"村里的大事本又厚了一页，都是我们一起写的。")
    return {"interests": interests, "new_vocab": produced + recognized,
            "emotions": [e for e, _ in emotion_counts.most_common(3)],
            "milestones": milestones or ["和玩偶的友情升温中"], "doll_diary_text": doll_diary}
