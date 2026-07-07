"""记忆服务：L1-L4 的读写 + 热路径「记忆包」组装。

硬约束：build_memory_pack 只做数据库读，零 LLM 调用，<50ms。
"""
import json

from . import db


# ---------------------------------------------------------------- L1 核心卡片

def get_card(child_id: int, card_type: str) -> dict:
    row = db.q1("SELECT payload_json FROM core_cards WHERE child_id=? AND type=?", (child_id, card_type))
    return db.jloads(row["payload_json"], {}) if row else {}


def save_card(child_id: int, card_type: str, payload: dict):
    db.execute(
        "INSERT INTO core_cards(child_id,type,payload_json,updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(child_id,type) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
        (child_id, card_type, json.dumps(payload, ensure_ascii=False), db.now()),
    )


def update_card(child_id: int, card_type: str, patch: dict):
    card = get_card(child_id, card_type)
    card.update(patch)
    save_card(child_id, card_type, card)
    return card


# ---------------------------------------------------------------- L2 情景日记

def add_diary(child_id: int, summary: str, emotions=None, topics=None, quotes=None,
              open_loop: str = "", ts: str | None = None) -> int:
    return db.execute(
        "INSERT INTO diary_entries(child_id,ts,summary,emotions_json,topics_json,quotes_json,open_loop) "
        "VALUES(?,?,?,?,?,?,?)",
        (child_id, ts or db.now(), summary,
         json.dumps(emotions or [], ensure_ascii=False),
         json.dumps(topics or [], ensure_ascii=False),
         json.dumps(quotes or [], ensure_ascii=False), open_loop),
    )


def list_diary(child_id: int, limit: int = 30):
    rows = db.q("SELECT * FROM diary_entries WHERE child_id=? ORDER BY ts DESC LIMIT ?", (child_id, limit))
    for r in rows:
        r["emotions"] = db.jloads(r.pop("emotions_json"))
        r["topics"] = db.jloads(r.pop("topics_json"))
        r["quotes"] = db.jloads(r.pop("quotes_json"))
    return rows


# ---------------------------------------------------------------- L3 事实

def add_fact(child_id: int, text: str, category: str, subject_key: str = "",
             confidence: float = 0.8, source: str = "", supersedes_key: str = "",
             valid_from: str | None = None) -> int:
    fid = db.execute(
        "INSERT INTO facts(child_id,text,category,subject_key,confidence,source,valid_from,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (child_id, text, category, subject_key, confidence, source, valid_from or db.today(), db.now()),
    )
    if supersedes_key:
        old = db.q1(
            "SELECT id FROM facts WHERE child_id=? AND subject_key=? AND superseded_by IS NULL AND id!=?",
            (child_id, supersedes_key, fid),
        )
        if old:
            db.execute("UPDATE facts SET superseded_by=? WHERE id=?", (fid, old["id"]))
    return fid


def list_facts(child_id: int, active_only: bool = False):
    sql = "SELECT * FROM facts WHERE child_id=?"
    if active_only:
        sql += " AND superseded_by IS NULL"
    return db.q(sql + " ORDER BY created_at DESC", (child_id,))


def search_facts(child_id: int, text: str, limit: int = 5):
    """轻量召回：关键词重叠打分（demo 不引向量库，保持零依赖）。"""
    facts = list_facts(child_id, active_only=True)
    if not text:
        return facts[:limit]
    scored = []
    for f in facts:
        score = sum(1 for token in set(f["text"]) & set(text) if not token.isascii())
        scored.append((score, f))
    scored.sort(key=lambda x: -x[0])
    return [f for s, f in scored[:limit]]


# ---------------------------------------------------------------- L4 成长快照

def add_snapshot(child_id: int, period: str, interests=None, new_vocab=None,
                 emotions=None, milestones=None, doll_diary_text: str = "") -> int:
    return db.execute(
        "INSERT INTO growth_snapshots(child_id,period,interests_json,new_vocab_json,emotions_json,"
        "milestones_json,doll_diary_text,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (child_id, period,
         json.dumps(interests or [], ensure_ascii=False),
         json.dumps(new_vocab or [], ensure_ascii=False),
         json.dumps(emotions or [], ensure_ascii=False),
         json.dumps(milestones or [], ensure_ascii=False),
         doll_diary_text, db.now()),
    )


def list_snapshots(child_id: int):
    rows = db.q("SELECT * FROM growth_snapshots WHERE child_id=? ORDER BY created_at DESC", (child_id,))
    for r in rows:
        r["interests"] = db.jloads(r.pop("interests_json"))
        r["new_vocab"] = db.jloads(r.pop("new_vocab_json"))
        r["emotions"] = db.jloads(r.pop("emotions_json"))
        r["milestones"] = db.jloads(r.pop("milestones_json"))
    return rows


# ---------------------------------------------------------------- 热路径记忆包

def build_memory_pack(child_id: int, first_message: str = "") -> dict:
    """开场一次性预取：孩子卡 + 玩偶卡 + 昨日日记 + 相关事实 + 议程 + 分享事件 + 记忆钩子。
    纯 DB 读，禁止任何 LLM 调用。"""
    child = db.q1("SELECT * FROM children WHERE id=?", (child_id,)) or {}
    diaries = list_diary(child_id, limit=3)
    yesterday = diaries[0] if diaries else None

    agenda = db.q1("SELECT * FROM session_agenda WHERE child_id=? AND date=?", (child_id, db.today()))
    review_items, share_event, interactive_question, memory_hook = [], None, "", ""
    if agenda:
        review_items = db.jloads(agenda["review_items_json"])
        memory_hook = agenda["memory_hook"] or ""
        if agenda["share_event_id"]:
            ev = db.q1("SELECT * FROM doll_events WHERE id=?", (agenda["share_event_id"],))
            if ev and ev["share_status"] == "unshared":
                share_event = {"id": ev["id"], "text": ev["text"], "vocab": db.jloads(ev["vocab_json"])}
                interactive_question = ev["interactive_question"] or ""
    if not memory_hook and yesterday and yesterday.get("open_loop"):
        memory_hook = yesterday["open_loop"]

    superseded = [
        {"以前": f["text"], "现在": (db.q1("SELECT text FROM facts WHERE id=?", (f["superseded_by"],)) or {}).get("text", "")}
        for f in db.q("SELECT * FROM facts WHERE child_id=? AND superseded_by IS NOT NULL ORDER BY created_at DESC LIMIT 3", (child_id,))
    ]

    recent_events = db.q(
        "SELECT text, share_status FROM doll_events WHERE child_id=? ORDER BY ts DESC LIMIT 4", (child_id,))

    return {
        "child_card": get_card(child_id, "child"),
        "doll_card": get_card(child_id, "doll"),
        "taboo": db.jloads(child.get("taboo_json", "[]")),
        "yesterday_diary": yesterday["summary"] if yesterday else "",
        "facts": [f["text"] for f in search_facts(child_id, first_message, limit=6)],
        "superseded_facts": superseded,
        "memory_hook": memory_hook,
        "canon": [f'{c["entity"]}：{c["fact_text"]}' for c in db.q(
            "SELECT entity,fact_text FROM doll_canon WHERE child_id=? ORDER BY id", (child_id,))],
        "recent_events": [e["text"] for e in recent_events if e["share_status"] != "unshared"][:3],
        "share_event": share_event,
        "interactive_question": interactive_question,
        "review_items": review_items,
    }
