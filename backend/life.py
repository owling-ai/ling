"""玩偶的数字生命 + 教材复习闭环（冷路径）。

- 夜间规划器 night_planner：从掌握度表挑 3-5 个到期项 → 今日议程 + 记忆钩子
- 基础世界时钟 life_tick：只按统一时间槽投影公共事件，不读取孩子私有记忆
- 私有成长时钟 advance_private_arc：仅由有意义互动显式触发
- SRS-lite：曝光/识别/产出三层计分，听懂间隔翻倍、没反应间隔重置
"""
import json
from datetime import datetime, timedelta

from . import db, llm, media, memory, prompts

CHILD_ID = db.CHILD_ID


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


# ---------------------------------------------------------------- 世界与私有成长时钟


def life_tick(
    child_id: int = CHILD_ID,
    *,
    now: datetime | None = None,
    timezone: str = "Asia/Shanghai",
) -> dict:
    """兼容旧调试入口：预览统一作息事件，不读写孩子私有事实。"""
    projection = media.default_catalog().select_world_event(
        f"ling-{child_id}",
        now or datetime.now().astimezone(),
        timezone,
    )
    event = projection["event"]
    return {
        "mode": projection["mode"],
        "timezone": projection["timezone"],
        "next_transition_at": projection["next_transition_at"],
        "event_id": event["event_id"],
        "event_version": event["event_version"],
        "variant_id": event["variant_id"],
        "text": event["summary"],
        "media": event["media"],
    }


def advance_private_arc(child_id: int) -> dict | None:
    """Advance one private story beat after a meaningful child interaction."""
    with db.transaction(immediate=True) as conn:
        row = conn.execute(
            "SELECT * FROM doll_arcs WHERE child_id=? AND status='active' "
            "ORDER BY id LIMIT 1",
            (child_id,),
        ).fetchone()
        if row is None:
            return None
        arc = dict(row)
        beats = db.jloads(arc["beats_json"])
        new_beat = min(arc["current_beat"] + 1, len(beats))
        status = "done" if new_beat >= len(beats) else "active"
        conn.execute(
            "UPDATE doll_arcs SET current_beat=?,status=? WHERE id=?",
            (new_beat, status, arc["id"]),
        )
    return {"arc_id": arc["id"], "current_beat": new_beat, "status": status}


def commit_private_choice(
    child_id: int,
    *,
    source_key: str,
    event_id: int | None,
    entity: str,
    fact_text: str,
    child_reaction: str,
) -> dict:
    """Atomically record one confirmed child choice and its private story advance."""
    with db.transaction(immediate=True) as conn:
        existing = conn.execute(
            "SELECT id FROM doll_canon WHERE source_key=?", (source_key,)
        ).fetchone()
        if existing:
            return {"created": False, "canon_id": existing["id"], "arc": None}

        canon_id = conn.execute(
            "INSERT INTO doll_canon("
            "child_id,entity,fact_text,by_child,established_at,source_key"
            ") VALUES(?,?,?,?,?,?)",
            (child_id, entity, fact_text, 1, db.now(), source_key),
        ).lastrowid
        row = conn.execute(
            "SELECT * FROM doll_arcs WHERE child_id=? AND status='active' "
            "ORDER BY id LIMIT 1",
            (child_id,),
        ).fetchone()
        arc_result = None
        if row is not None:
            arc = dict(row)
            beats = db.jloads(arc["beats_json"])
            new_beat = min(arc["current_beat"] + 1, len(beats))
            status = "done" if new_beat >= len(beats) else "active"
            conn.execute(
                "UPDATE doll_arcs SET current_beat=?,status=? WHERE id=?",
                (new_beat, status, arc["id"]),
            )
            arc_result = {
                "arc_id": arc["id"],
                "current_beat": new_beat,
                "status": status,
            }
        if event_id is not None:
            updated = conn.execute(
                "UPDATE doll_events SET child_reaction=? WHERE id=? AND child_id=?",
                (child_reaction, event_id, child_id),
            ).rowcount
            if updated != 1:
                raise ValueError("choice event not found")
    return {"created": True, "canon_id": canon_id, "arc": arc_result}


def add_canon(
    child_id: int,
    entity: str,
    fact_text: str,
    by_child: bool,
    source_key: str | None = None,
) -> int:
    return db.execute(
        "INSERT INTO doll_canon("
        "child_id,entity,fact_text,by_child,established_at,source_key"
        ") VALUES(?,?,?,?,?,?)",
        (child_id, entity, fact_text, 1 if by_child else 0, db.now(), source_key),
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
                             ensure_ascii=False))) if llm.worker_live() else None
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
