from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event, Lock

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
    body = EndBody(session_id=session_id)
    start = Barrier(3)

    def end_session() -> dict:
        start.wait()
        return session_end(body)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(end_session) for _ in range(2)]
        start.wait()
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


def test_openai_worker_without_real_key_uses_mock_rules_for_session_end(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed.seed()
    engine.SESSIONS.clear()
    for name in (
        "LING_PROVIDER",
        "LING_WORKER_BASE_URL",
        "LING_OPENAI_BASE_URL",
        "LING_WORKER_API_KEY",
        "LING_OPENAI_API_KEY",
        "LING_WORKER_MODEL",
        "LING_OPENAI_MODEL",
        "LING_WORKER_ALLOW_EMPTY_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        llm,
        "WORKER_EP",
        {
            "base": "https://example.invalid/v1",
            "key": "EMPTY",
            "model": "demo-worker",
        },
    )
    monkeypatch.setattr(llm, "_get_anthropic", lambda: None)

    def fail_if_network_worker_is_used(*args, **kwargs):
        raise AssertionError("session_end should use local mock rules without a key")

    monkeypatch.setattr(llm, "worker_json", fail_if_network_worker_is_used)
    started = engine.start_session(db.CHILD_ID)
    session_id = started["session_id"]
    engine.record_voice_user(session_id, "我最喜欢风筝")

    result = session_end(EndBody(session_id=session_id))

    assert result["diary"]["summary"]
    assert result["new_facts"] == ["喜欢风筝"]
    assert db.q1(
        "SELECT processed,processing FROM sessions WHERE id=?",
        (engine.SESSIONS[session_id]["db_id"],),
    ) == {"processed": 1, "processing": 0}
    engine.SESSIONS.clear()


def test_concurrent_live_session_end_calls_worker_once_and_reuses_result(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed.seed()
    engine.SESSIONS.clear()
    monkeypatch.setattr(llm, "worker_live", lambda: True)
    calls = []
    calls_lock = Lock()
    start = Barrier(3)
    worker_started = Event()
    release_worker = Event()

    def controlled_worker_json(prompt: str, *args, **kwargs):
        with calls_lock:
            calls.append(prompt)
            call_number = len(calls)
        if call_number == 1:
            worker_started.set()
            assert release_worker.wait(timeout=5)
        if "日记" in prompt or "summary" in prompt:
            return {
                "summary": "悠悠和灵灵聊了熊猫。",
                "emotions": ["开心"],
                "topics": ["动物"],
                "quotes": [],
                "open_loop": "",
            }
        return [
            {
                "text": "喜欢熊猫",
                "category": "interest",
                "subject_key": "熊猫",
                "confidence": 0.8,
            }
        ]

    monkeypatch.setattr(llm, "worker_json", controlled_worker_json)
    started = engine.start_session(db.CHILD_ID)
    session_id = started["session_id"]
    engine.record_voice_user(session_id, "panda，我最喜欢熊猫")
    engine.record_voice_doll(session_id, "panda 是熊猫呀")
    session_db_id = engine.SESSIONS[session_id]["db_id"]
    body = EndBody(session_id=session_id)

    def end_session() -> dict:
        start.wait()
        return session_end(body)

    pool = ThreadPoolExecutor(max_workers=2)
    try:
        futures = [pool.submit(end_session) for _ in range(2)]
        start.wait()
        assert worker_started.wait(timeout=5)
        assert db.q1(
            "SELECT processed,processing FROM sessions WHERE id=?", (session_db_id,)
        ) == {"processed": 0, "processing": 1}
        with calls_lock:
            assert len(calls) == 1
        release_worker.set()
        results = [future.result(timeout=5) for future in futures]
    finally:
        release_worker.set()
        pool.shutdown(wait=True, cancel_futures=True)

    assert results[0] == results[1]
    assert len(calls) == 2
    assert db.q1(
        "SELECT COUNT(*) AS n FROM facts WHERE source=?",
        (f"session:{session_db_id}",),
    ) == {"n": 1}
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
