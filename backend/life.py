"""玩偶的数字生命 + 教材复习闭环（冷路径）。

- 夜间规划器 night_planner：从掌握度表挑 3-5 个到期项 → 今日议程 + 记忆钩子
- 生活时钟 life_tick：每天推进故事弧一拍，结合正典与复习议程生成生活事件（不管孩子来没来）
- SRS-lite：曝光/识别/产出三层计分，听懂间隔翻倍、没反应间隔重置
"""
import json
import random
from datetime import datetime, timedelta

from . import db, llm, memory, prompts

CHILD_ID = 1


# ---------------------------------------------------------------- SRS-lite

def ensure_mastery_rows(child_id: int):
    """把当前单元的学习项落进掌握度表。"""
    state = db.q1("SELECT * FROM learning_state WHERE child_id=?", (child_id,))
    if not state:
        return
    pack = db.q1("SELECT * FROM curriculum_packs WHERE id=?", (state["pack_id"],))
    if not pack:
        return
    units = db.jloads(pack["units_json"])
    unit = next((u for u in units if u["unit"] == state["current_unit"]), None)
    if not unit:
        return
    for w in unit["words"]:
        item_id = f'u{unit["unit"]}:word:{w["word"]}'
        db.execute(
            "INSERT OR IGNORE INTO item_mastery(child_id,item_id,item_text,item_zh,item_type,due_date) "
            "VALUES(?,?,?,?,?,?)",
            (child_id, item_id, w["word"], w["zh"], "word", db.today()),
        )
    for p in unit.get("patterns", []):
        item_id = f'u{unit["unit"]}:pattern:{p["pattern"]}'
        db.execute(
            "INSERT OR IGNORE INTO item_mastery(child_id,item_id,item_text,item_zh,item_type,due_date) "
            "VALUES(?,?,?,?,?,?)",
            (child_id, item_id, p["pattern"], p["zh"], "pattern", db.today()),
        )


LEVEL_ORDER = ["new", "exposed", "recognized", "produced"]


def record_mastery(child_id: int, item_id: str, result: str):
    """result: exposed | recognized | produced | none"""
    row = db.q1("SELECT * FROM item_mastery WHERE child_id=? AND item_id=?", (child_id, item_id))
    if not row:
        return
    exposures = row["exposures"] + 1
    successes = row["successes"]
    interval = row["interval_days"]
    level = row["level"]
    if result in ("recognized", "produced"):
        successes += 1
        interval = min(interval * 2, 30)   # 听懂了 → 间隔翻倍
    else:
        interval = 1                        # 没反应 → 间隔重置
    if result in LEVEL_ORDER and LEVEL_ORDER.index(result) > LEVEL_ORDER.index(level):
        level = result
    due = (datetime.now() + timedelta(days=interval)).strftime("%Y-%m-%d")
    db.execute(
        "UPDATE item_mastery SET exposures=?,successes=?,interval_days=?,level=?,last_seen=?,due_date=? "
        "WHERE child_id=? AND item_id=?",
        (exposures, successes, interval, level, db.now(), due, child_id, item_id),
    )


def due_items(child_id: int, limit: int = 5):
    return db.q(
        "SELECT * FROM item_mastery WHERE child_id=? AND due_date<=? "
        "ORDER BY CASE item_type WHEN 'word' THEN 0 ELSE 1 END, "
        "CASE level WHEN 'new' THEN 0 WHEN 'exposed' THEN 1 WHEN 'recognized' THEN 2 ELSE 3 END, due_date "
        "LIMIT ?",
        (child_id, db.today(), limit),
    )


# ---------------------------------------------------------------- 生活时钟

def _mock_life_event(doll_card, canon_rows, arc, next_beat, review_words, child_topics):
    """无 LLM 时的事件生成：故事拍模板 + 目标词场景化织入。"""
    friends = [c["entity"] for c in canon_rows if "先生" in c["entity"] or "阿姨" in c["entity"] or "小姐" in c["entity"]]
    friend = random.choice(friends) if friends else "松鼠先生"
    weave = []
    for w in review_words[:2]:
        weave.append(f'{w["item_text"]}（就是{w["item_zh"]}呀）')
    weave_txt = "、".join(weave) if weave else ""
    beat_txt = next_beat or "村子里过了平静的一天"
    mirror = f"我想起你最近老提到{child_topics[0]}，" if child_topics else ""
    text = f"今天{friend}和我一起：{beat_txt}。{mirror}路上我们还遇到了 {weave_txt}！" if weave_txt \
        else f"今天{friend}和我一起：{beat_txt}。"
    question = f"你说，{beat_txt.split('，')[0]}之后，我们接下来该怎么办呀？"
    return {
        "text": text,
        "vocab": [w["item_text"] for w in review_words[:2]],
        "interactive_question": question,
        "new_canon": [],
    }


def life_tick(child_id: int = CHILD_ID) -> dict:
    """推进一拍，生成今天的生活事件。每天都跑，不管孩子来没来。"""
    doll_card = memory.get_card(child_id, "doll")
    canon_rows = db.q("SELECT * FROM doll_canon WHERE child_id=? ORDER BY id", (child_id,))
    arc = db.q1("SELECT * FROM doll_arcs WHERE child_id=? AND status='active' ORDER BY id LIMIT 1", (child_id,))
    beats = db.jloads(arc["beats_json"]) if arc else []
    next_beat = beats[arc["current_beat"]] if arc and arc["current_beat"] < len(beats) else ""

    review = due_items(child_id, 3)
    review_words = [r for r in review if r["item_type"] == "word"]
    diaries = memory.list_diary(child_id, 3)
    child_topics = [t for d in diaries for t in d["topics"]][:2]

    result = llm.worker_json(prompts.LIFE_TICK_PROMPT.format(
        doll_name=doll_card.get("name", "灵灵"),
        canon=json.dumps([f'{c["entity"]}：{c["fact_text"]}' for c in canon_rows], ensure_ascii=False),
        arc_title=arc["title"] if arc else "平静的日常",
        next_beat=next_beat or "（无，自由发挥一件小事）",
        review_items=json.dumps([{"word": w["item_text"], "zh": w["item_zh"]} for w in review_words], ensure_ascii=False),
        child_topics=json.dumps(child_topics, ensure_ascii=False),
    )) if llm.live_mode() else None
    if not isinstance(result, dict) or "text" not in result:
        result = _mock_life_event(doll_card, canon_rows, arc, next_beat, review_words, child_topics)

    event_id = db.execute(
        "INSERT INTO doll_events(child_id,ts,text,arc_id,vocab_json,interactive_question) VALUES(?,?,?,?,?,?)",
        (child_id, db.now(), result["text"], arc["id"] if arc else None,
         json.dumps(result.get("vocab", []), ensure_ascii=False),
         result.get("interactive_question", "")),
    )
    # 未分享事件最多攒 3 条，久的沉淀进档案，回来时不倒垃圾
    stale = db.q(
        "SELECT id FROM doll_events WHERE child_id=? AND share_status='unshared' ORDER BY ts DESC LIMIT -1 OFFSET 3",
        (child_id,))
    for s in stale:
        db.execute("UPDATE doll_events SET share_status='archived' WHERE id=?", (s["id"],))

    if arc:
        new_beat = arc["current_beat"] + 1
        status = "done" if new_beat >= len(beats) else "active"
        db.execute("UPDATE doll_arcs SET current_beat=?, status=? WHERE id=?", (new_beat, status, arc["id"]))
    for c in result.get("new_canon", []):
        add_canon(child_id, c.get("entity", ""), c.get("fact_text", ""), by_child=False)
    return {"event_id": event_id, **result}


def add_canon(child_id: int, entity: str, fact_text: str, by_child: bool) -> int:
    return db.execute(
        "INSERT INTO doll_canon(child_id,entity,fact_text,by_child,established_at) VALUES(?,?,?,?,?)",
        (child_id, entity, fact_text, 1 if by_child else 0, db.now()),
    )


# ---------------------------------------------------------------- 夜间规划器

def night_planner(child_id: int = CHILD_ID, date: str | None = None) -> dict:
    """挑到期复习项 + 选待分享事件 + 生成记忆钩子 → 写入今日议程。"""
    ensure_mastery_rows(child_id)
    date = date or db.today()
    items = due_items(child_id, 5)
    review_items = [
        {"item_id": r["item_id"], "word": r["item_text"], "zh": r["item_zh"],
         "type": r["item_type"], "level": r["level"]}
        for r in items
    ]

    ev = db.q1(
        "SELECT * FROM doll_events WHERE child_id=? AND share_status='unshared' ORDER BY ts DESC LIMIT 1",
        (child_id,))

    diaries = memory.list_diary(child_id, 1)
    hook = ""
    if diaries:
        d = diaries[0]
        result = llm.worker_json(prompts.HOOK_PROMPT.format(
            diary=json.dumps({"summary": d["summary"], "quotes": d["quotes"], "open_loop": d["open_loop"]},
                             ensure_ascii=False))) if llm.live_mode() else None
        if isinstance(result, dict) and result.get("hook"):
            hook = result["hook"]
        elif d.get("open_loop"):
            hook = d["open_loop"]
        elif d["topics"]:
            hook = f'昨天我们聊了{d["topics"][0]}，我睡觉前还在想呢！今天你过得怎么样？'

    db.execute(
        "INSERT INTO session_agenda(child_id,date,review_items_json,share_event_id,memory_hook,status) "
        "VALUES(?,?,?,?,?,'ready') "
        "ON CONFLICT(child_id,date) DO UPDATE SET review_items_json=excluded.review_items_json, "
        "share_event_id=excluded.share_event_id, memory_hook=excluded.memory_hook, status='ready'",
        (child_id, date, json.dumps(review_items, ensure_ascii=False), ev["id"] if ev else None, hook),
    )
    return {"date": date, "review_items": review_items,
            "share_event": ev["text"] if ev else None, "memory_hook": hook}


# ---------------------------------------------------------------- 关系成长

STAGES = ["new_friend", "good_friend", "best_friend"]


def add_relationship_xp(child_id: int, xp: int) -> dict:
    card = memory.get_card(child_id, "doll")
    card["relationship_xp"] = card.get("relationship_xp", 0) + xp
    thresholds = {0: "new_friend", 30: "good_friend", 80: "best_friend"}
    stage = card.get("relationship_stage", "new_friend")
    for t in sorted(thresholds):
        if card["relationship_xp"] >= t:
            stage = thresholds[t]
    leveled = stage != card.get("relationship_stage")
    card["relationship_stage"] = stage
    memory.save_card(child_id, "doll", card)
    return {"stage": stage, "xp": card["relationship_xp"], "leveled_up": leveled}
