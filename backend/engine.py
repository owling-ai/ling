"""会话状态 + 编织追踪器（热路径）。

对话本体发生在实时音视频会话里（Gemini / StepFun / MiniCPM / 火山 RTC），这里只负责：
- 开场：一次 DB 读组装记忆包（人设注入的原料），零 LLM。
- 记账：双向转写喂进编织追踪器 —— 曝光/识别/产出、分享事件、互动拍、
  撤退规则、正典写回，全部在这里落地，与语音链路解耦。
"""
import json
import re
import threading
import uuid
import weakref
from collections import OrderedDict

from . import db, life, memory

SESSIONS: dict[str, dict] = {}
CLOSED_SESSION_LIMIT = 32

_CLOSED_SESSION_ORDER: OrderedDict[str, None] = OrderedDict()
_SESSIONS_GUARD = threading.Lock()
_SESSION_LOCKS = weakref.WeakValueDictionary()
_SESSION_LOCKS_GUARD = threading.Lock()

RETREAT_WORDS = ["不想", "无聊", "别说英语", "不要英语", "烦", "不学", "别教"]
POSITIVE_ACKS = ["好", "哇", "喜欢", "真", "酷", "棒", "想", "嗯"]


def _initial_runtime_state() -> dict:
    return {
        "woven": [],
        "produced": [],
        "shared": False,
        "pending_choice": False,
        "retreated": False,
        "canon_written": [],
        "idle_nudges": 0,
        "turn": 0,
        "choice_done": False,
        "opening_sent": False,
    }


def _runtime_state(session: dict) -> dict:
    return {
        "woven": list(session.get("woven") or []),
        "produced": list(session.get("produced") or []),
        "shared": bool(session.get("shared")),
        "pending_choice": bool(session.get("pending_choice")),
        "retreated": bool(session.get("retreated")),
        "canon_written": list(session.get("canon_written") or []),
        "idle_nudges": int(session.get("idle_nudges", 0)),
        "turn": int(session.get("turn", 0)),
        "choice_done": bool(session.get("choice_done")),
        "opening_sent": bool(session.get("opening_sent")),
    }


def _restore_session(row: dict) -> dict:
    state = db.jloads(row.get("state_json"), {})
    if not isinstance(state, dict):
        state = {}
    runtime = _initial_runtime_state()
    for key in runtime:
        if key in state:
            runtime[key] = state[key]

    pack = db.jloads(row.get("pack_json"), {})
    if not isinstance(pack, dict) or not pack:
        pack = memory.build_memory_pack(row["child_id"])
    history = db.jloads(row.get("transcript_json"), [])
    if not isinstance(history, list):
        history = []
    return {
        "session_id": row.get("session_key"),
        "db_id": row["id"],
        "child_id": row["child_id"],
        "pack": pack,
        "history": history,
        "gemini_resumption_handle": row.get("gemini_resumption_handle"),
        **runtime,
    }


def _persist_runtime(session: dict) -> None:
    db.execute(
        "UPDATE sessions SET transcript_json=?,state_json=? WHERE id=?",
        (
            json.dumps(session["history"], ensure_ascii=False),
            json.dumps(_runtime_state(session), ensure_ascii=False),
            session["db_id"],
        ),
    )


# ---------------------------------------------------------------- 会话生命周期


def _session_lock(session_id: str):
    with _SESSION_LOCKS_GUARD:
        lock = _SESSION_LOCKS.get(session_id)
        if lock is None:
            lock = threading.RLock()
            _SESSION_LOCKS[session_id] = lock
        return lock


def _is_closed(session: dict | None) -> bool:
    return bool(session and session.get("closed") is True)


def _active_session(session_id: str) -> dict | None:
    with _SESSIONS_GUARD:
        session = SESSIONS.get(session_id)
    return None if _is_closed(session) or (session and session.get("closing")) else session


def _prune_closed_sessions() -> None:
    while len(_CLOSED_SESSION_ORDER) > CLOSED_SESSION_LIMIT:
        oldest_id, _ = _CLOSED_SESSION_ORDER.popitem(last=False)
        if _is_closed(SESSIONS.get(oldest_id)):
            SESSIONS.pop(oldest_id, None)


def start_session(child_id: int) -> dict:
    pack = memory.build_memory_pack(child_id)
    session_id = uuid.uuid4().hex[:12]
    child_name = pack["child_card"].get("name", "小朋友")
    doll_name = pack["doll_card"].get("name", "灵灵")
    opening = f"嗨，{child_name}，{doll_name}在呢！"
    runtime = _initial_runtime_state()

    # 实际开场由实时模型生成并通过 record_voice_doll 入库；这里不能预写一条
    # 孩子尚未听到的记忆钩子，否则冷路径会处理出“幽灵转写”。
    sid = db.execute(
        "INSERT INTO sessions("
        "child_id,started_at,transcript_json,session_key,pack_json,state_json"
        ") VALUES(?,?,?,?,?,?)",
        (
            child_id,
            db.now(),
            "[]",
            session_id,
            json.dumps(pack, ensure_ascii=False),
            json.dumps(runtime, ensure_ascii=False),
        ),
    )
    session = {
        "session_id": session_id,
        "db_id": sid,
        "child_id": child_id,
        "pack": pack,
        "history": [],
        **runtime,
        "gemini_resumption_handle": None,
    }
    with _SESSIONS_GUARD:
        SESSIONS[session_id] = session
        _CLOSED_SESSION_ORDER.pop(session_id, None)
    db.execute("UPDATE session_agenda SET status='consumed' WHERE child_id=? AND date=?",
               (child_id, db.today()))
    return {"session_id": session_id, "opening": opening, "memory_pack": pack}


def get_session(session_id: str):
    lock = _session_lock(session_id)
    with lock:
        with _SESSIONS_GUARD:
            present = session_id in SESSIONS
        if present:
            return _active_session(session_id)

        # 设备会在后端重启后复用业务 session ID。只有未结束的 DB 会话可以恢复；
        # 已关闭会话仍是幂等墓碑，不能被重新打开。
        row = db.q1(
            "SELECT * FROM sessions "
            "WHERE session_key=? AND ended_at IS NULL AND processed=0",
            (session_id,),
        )
        if not row:
            return None
        session = _restore_session(row)
        with _SESSIONS_GUARD:
            existing = SESSIONS.get(session_id)
            if existing is None:
                SESSIONS[session_id] = session
                return session
            return _active_session(session_id)


def get_session_history(session_id: str) -> list[dict]:
    with _session_lock(session_id):
        session = _active_session(session_id)
        if not session:
            return []
        return [
            dict(item)
            for item in session.get("history", [])
            if isinstance(item, dict)
        ]


def claim_opening(session_id: str) -> bool:
    """Claim the one-time opening across reconnects and process restarts."""
    with _session_lock(session_id):
        session = _active_session(session_id)
        if not session or session.get("opening_sent"):
            return False
        session["opening_sent"] = True
        _persist_runtime(session)
        return True


def gemini_resumption_handle(session_id: str) -> str | None:
    with _session_lock(session_id):
        session = _active_session(session_id)
        return session.get("gemini_resumption_handle") if session else None


def update_gemini_resumption_handle(
    session_id: str, handle: str | None, *, expected: str | None = None
) -> bool:
    """Persist the newest provider handle without overwriting a newer connection."""
    with _session_lock(session_id):
        session = _active_session(session_id)
        if not session:
            return False
        current = session.get("gemini_resumption_handle")
        if expected is not None and current != expected:
            return False
        session["gemini_resumption_handle"] = handle or None
        db.execute(
            "UPDATE sessions SET gemini_resumption_handle=?,"
            "gemini_resumption_updated_at=? WHERE id=?",
            (handle or None, db.now(), session["db_id"]),
        )
        return True


def close_session(session_id: str, finalize_callback):
    """Finalize once, then retain only a bounded idempotency tombstone."""
    with _session_lock(session_id):
        with _SESSIONS_GUARD:
            session = SESSIONS.get(session_id)
            if _is_closed(session):
                return session["result"]
            if session is None:
                row = db.q1(
                    "SELECT * FROM sessions "
                    "WHERE session_key=? AND ended_at IS NULL AND processed=0",
                    (session_id,),
                )
                if not row:
                    return None
                session = _restore_session(row)
                with _SESSIONS_GUARD:
                    SESSIONS[session_id] = session
            session["closing"] = True

        result = finalize_callback(session)

        with _SESSIONS_GUARD:
            SESSIONS[session_id] = {"closed": True, "result": result}
            _CLOSED_SESSION_ORDER.pop(session_id, None)
            _CLOSED_SESSION_ORDER[session_id] = None
            _prune_closed_sessions()
        return result


def claim_idle_nudge(session_id: str, limit: int = 2) -> int | None:
    """领取一次冷场主动发言预算，返回本场第几次；超限时返回 None。"""
    with _session_lock(session_id):
        session = _active_session(session_id)
        if not session or session.get("idle_nudges", 0) >= limit:
            return None
        session["idle_nudges"] = session.get("idle_nudges", 0) + 1
        _persist_runtime(session)
        return session["idle_nudges"]


def _save_transcript(s):
    _persist_runtime(s)


def _state_dict(s) -> dict:
    return {
        "woven": list(s["woven"]),
        "produced": list(s["produced"]),
        "shared": s["shared"],
        "pending_choice": s["pending_choice"],
        "retreated": s["retreated"],
        "canon_written": s["canon_written"],
    }


# ---------------------------------------------------------------- 语音转写记账入口
# 对话本体发生在上游 WS 会话里，这里只接收双向转写：
# 记账（编织追踪）+ 历史 + 落库，让记忆闭环与语音链路完全解耦。

def record_voice_user(session_id: str, text: str):
    with _session_lock(session_id):
        s = _active_session(session_id)
        text = (text or "").strip()
        if not s or not text:
            return
        s["turn"] += 1
        _track_child_message(s, text)
        s["history"].append({"role": "user", "content": text})
        _save_transcript(s)


def record_voice_doll(session_id: str, text: str) -> dict | None:
    with _session_lock(session_id):
        s = _active_session(session_id)
        text = (text or "").strip()
        if not s or not text:
            return None
        _track_doll_reply(s, text)
        s["history"].append({"role": "assistant", "content": text})
        _save_transcript(s)
        return _state_dict(s)


# ---------------------------------------------------------------- 编织追踪器

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
            if r["word"] not in s["produced"]:
                s["produced"].append(r["word"])
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
        ev = s["pack"].get("share_event") or {}
        entity = _guess_entity(s)
        canon_text = f"{s['pack']['child_card'].get('name','孩子')}决定：{text.strip()[:40]}"
        source_key = f"session:{s['db_id']}:event:{ev.get('id') or 'choice'}"
        life.commit_private_choice(
            child_id,
            source_key=source_key,
            event_id=ev.get("id"),
            entity=entity,
            fact_text=canon_text,
            child_reaction=text.strip()[:60],
        )
        if {"entity": entity, "fact_text": canon_text} not in s["canon_written"]:
            s["canon_written"].append({"entity": entity, "fact_text": canon_text})
        s["choice_done"] = True
        s["pending_choice"] = False


def _guess_entity(s):
    ev = s["pack"].get("share_event") or {}
    canon = s["pack"].get("canon") or []
    for line in canon:
        entity = line.split("：")[0]
        if entity and entity in (ev.get("text") or ""):
            return entity
    return "我们的故事"
