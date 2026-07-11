from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from backend import db, engine, llm, memory, seed, workers
from backend.app import EndBody, session_end


def _close_main_connection() -> None:
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        delattr(db._local, "conn")


def test_init_db_migrates_old_sessions_table_with_processing_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _close_main_connection()
    path = tmp_path / "old-ling.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE sessions("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,child_id INTEGER,started_at TEXT,"
        "ended_at TEXT,transcript_json TEXT DEFAULT '[]',processed INTEGER DEFAULT 0,"
        "cold_result_json TEXT DEFAULT '{}')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", str(path))

    db.init_db()

    columns = {row["name"] for row in db.q("PRAGMA table_info(sessions)")}
    assert {"processing", "processing_started_at"} <= columns
    _close_main_connection()


def test_concurrent_session_end_derives_memory_and_mastery_once(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed.seed()
    engine.SESSIONS.clear()
    monkeypatch.setattr(llm, "worker_live", lambda: False)
    started = engine.start_session(db.CHILD_ID)
    session_id = started["session_id"]
    engine.record_voice_user(session_id, "panda，我最喜欢熊猫")
    engine.record_voice_doll(session_id, "panda 是熊猫呀")
    session_db_id = engine.SESSIONS[session_id]["db_id"]

    diary_before = db.q1("SELECT COUNT(*) AS n FROM diary_entries")["n"]
    facts_before = db.q1(
        "SELECT COUNT(*) AS n FROM facts WHERE source=?", (f"session:{session_db_id}",)
    )["n"]
    mastery_before = db.q1(
        "SELECT exposures FROM item_mastery WHERE child_id=? AND item_id='u4:word:panda'",
        (db.CHILD_ID,),
    )["exposures"]
    xp_before = memory.get_card(db.CHILD_ID, "doll")["relationship_xp"]
    real_mock_diary = workers._mock_diary

    def slow_mock_diary(*args, **kwargs):
        time.sleep(0.05)
        return real_mock_diary(*args, **kwargs)

    monkeypatch.setattr(workers, "_mock_diary", slow_mock_diary)
    body = EndBody(session_id=session_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(session_end, body) for _ in range(2)]
        results = [future.result(timeout=5) for future in futures]

    assert results[0] == results[1]
    assert db.q1("SELECT COUNT(*) AS n FROM diary_entries") == {"n": diary_before + 1}
    assert db.q1(
        "SELECT COUNT(*) AS n FROM facts WHERE source=?", (f"session:{session_db_id}",)
    ) == {"n": facts_before + 1}
    assert db.q1(
        "SELECT exposures FROM item_mastery WHERE child_id=? AND item_id='u4:word:panda'",
        (db.CHILD_ID,),
    ) == {"exposures": mastery_before + 1}
    assert memory.get_card(db.CHILD_ID, "doll")["relationship_xp"] == xp_before + 5
    assert db.q1(
        "SELECT processed,processing FROM sessions WHERE id=?", (session_db_id,)
    ) == {"processed": 1, "processing": 0}
    engine.SESSIONS.clear()


def test_crashed_session_derivation_rolls_back_and_retry_writes_once(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed.seed()
    engine.SESSIONS.clear()
    monkeypatch.setattr(llm, "worker_live", lambda: False)
    started = engine.start_session(db.CHILD_ID)
    session_id = started["session_id"]
    engine.record_voice_user(session_id, "我最喜欢风筝")
    session_db_id = engine.SESSIONS[session_id]["db_id"]
    diary_before = db.q1("SELECT COUNT(*) AS n FROM diary_entries")["n"]
    xp_before = memory.get_card(db.CHILD_ID, "doll")["relationship_xp"]
    real_add_fact = workers.memory.add_fact

    def crash_after_diary(*args, **kwargs):
        raise RuntimeError("simulated crash after diary")

    monkeypatch.setattr(workers.memory, "add_fact", crash_after_diary)
    with pytest.raises(RuntimeError, match="simulated crash after diary"):
        session_end(EndBody(session_id=session_id))

    assert db.q1("SELECT COUNT(*) AS n FROM diary_entries") == {"n": diary_before}
    assert memory.get_card(db.CHILD_ID, "doll")["relationship_xp"] == xp_before
    assert db.q1(
        "SELECT processed,processing FROM sessions WHERE id=?", (session_db_id,)
    ) == {"processed": 0, "processing": 0}

    monkeypatch.setattr(workers.memory, "add_fact", real_add_fact)
    result = session_end(EndBody(session_id=session_id))
    repeated = session_end(EndBody(session_id=session_id))
    assert result == repeated
    assert db.q1("SELECT COUNT(*) AS n FROM diary_entries") == {"n": diary_before + 1}
    assert db.q1(
        "SELECT COUNT(*) AS n FROM facts WHERE source=?", (f"session:{session_db_id}",)
    ) == {"n": 1}
    assert memory.get_card(db.CHILD_ID, "doll")["relationship_xp"] == xp_before + 5
    engine.SESSIONS.clear()
