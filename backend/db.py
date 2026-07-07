"""SQLite 数据层：五层记忆 + 教材/掌握度 + 玩偶数字生命 的全部表结构。

设计要点（来自架构讨论）：
- L1 core_cards      常驻 prompt 的孩子卡/玩偶状态卡（性格稳定性的锚）
- L2 diary_entries   情景日记，append-only，产品灵魂；"一日一叶"/家长报告全从这出
- L3 facts           事实记忆，valid_from/superseded_by —— 成长感藏在被作废的旧事实里
- L4 growth_snapshots 反思/成长层，含玩偶视角日记
- 教材：curriculum_packs + learning_state + item_mastery（SRS-lite）
- 数字生命：doll_canon（世界正典）+ doll_arcs（故事弧）+ doll_events（生活事件）
- session_agenda     夜间规划器产出的"今日议程"，热路径开场纯 DB 读
"""
import json
import os
import sqlite3
import threading
from datetime import datetime

DB_PATH = os.environ.get("LING_DB", os.path.join(os.path.dirname(__file__), "..", "data", "ling.db"))

_local = threading.local()


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS children (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    age INTEGER,
    grade TEXT,
    family_json TEXT DEFAULT '[]',
    interests_json TEXT DEFAULT '[]',
    taboo_json TEXT DEFAULT '[]',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS core_cards (
    child_id INTEGER,
    type TEXT,                      -- 'child' | 'doll'
    payload_json TEXT,
    updated_at TEXT,
    PRIMARY KEY (child_id, type)
);

CREATE TABLE IF NOT EXISTS diary_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id INTEGER,
    ts TEXT,
    summary TEXT,
    emotions_json TEXT DEFAULT '[]',
    topics_json TEXT DEFAULT '[]',
    quotes_json TEXT DEFAULT '[]',
    open_loop TEXT DEFAULT ''       -- 未完成的悬念，记忆钩子的原料
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id INTEGER,
    text TEXT,
    category TEXT,                  -- interest / family / fear / friend / habit ...
    subject_key TEXT DEFAULT '',    -- 同一主题的新旧事实靠它对上号
    confidence REAL DEFAULT 0.8,
    source TEXT DEFAULT '',
    valid_from TEXT,
    superseded_by INTEGER,          -- 指向替代它的新事实；非 NULL 即"历史"
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS growth_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id INTEGER,
    period TEXT,
    interests_json TEXT DEFAULT '[]',
    new_vocab_json TEXT DEFAULT '[]',
    emotions_json TEXT DEFAULT '[]',
    milestones_json TEXT DEFAULT '[]',
    doll_diary_text TEXT DEFAULT '',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS curriculum_packs (
    id TEXT PRIMARY KEY,
    publisher TEXT,
    grade TEXT,
    semester TEXT,
    title TEXT,
    units_json TEXT
);

CREATE TABLE IF NOT EXISTS learning_state (
    child_id INTEGER PRIMARY KEY,
    pack_id TEXT,
    current_unit INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS item_mastery (
    child_id INTEGER,
    item_id TEXT,                   -- e.g. 'u4:word:panda'
    item_text TEXT,
    item_zh TEXT DEFAULT '',
    item_type TEXT DEFAULT 'word',  -- word | pattern
    level TEXT DEFAULT 'new',       -- new | exposed | recognized | produced
    exposures INTEGER DEFAULT 0,
    successes INTEGER DEFAULT 0,
    interval_days INTEGER DEFAULT 1,
    last_seen TEXT,
    due_date TEXT,
    PRIMARY KEY (child_id, item_id)
);

CREATE TABLE IF NOT EXISTS doll_canon (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id INTEGER,
    entity TEXT,                    -- 秋千 / 松鼠先生 / 橡树村 ...
    fact_text TEXT,
    by_child INTEGER DEFAULT 0,     -- 1 = 孩子的选择写进的正典
    established_at TEXT
);

CREATE TABLE IF NOT EXISTS doll_arcs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id INTEGER,
    title TEXT,
    beats_json TEXT,                -- 3-5 拍骨架
    current_beat INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active'    -- active | done
);

CREATE TABLE IF NOT EXISTS doll_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id INTEGER,
    ts TEXT,
    text TEXT,
    arc_id INTEGER,
    vocab_json TEXT DEFAULT '[]',   -- 事件里织入的目标词
    share_status TEXT DEFAULT 'unshared',  -- unshared | shared | archived
    child_reaction TEXT DEFAULT '',
    interactive_question TEXT DEFAULT ''   -- 互动拍：抛给孩子的难题
);

CREATE TABLE IF NOT EXISTS session_agenda (
    child_id INTEGER,
    date TEXT,
    review_items_json TEXT DEFAULT '[]',
    share_event_id INTEGER,
    memory_hook TEXT DEFAULT '',
    status TEXT DEFAULT 'ready',    -- ready | consumed
    PRIMARY KEY (child_id, date)
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id INTEGER,
    started_at TEXT,
    ended_at TEXT,
    transcript_json TEXT DEFAULT '[]',
    processed INTEGER DEFAULT 0,
    cold_result_json TEXT DEFAULT '{}'
);
"""


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def q(sql, params=()):
    return [dict(r) for r in get_conn().execute(sql, params).fetchall()]


def q1(sql, params=()):
    r = get_conn().execute(sql, params).fetchone()
    return dict(r) if r else None


def execute(sql, params=()):
    conn = get_conn()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid


def jloads(s, default=None):
    try:
        return json.loads(s) if s else (default if default is not None else [])
    except (TypeError, ValueError):
        return default if default is not None else []
