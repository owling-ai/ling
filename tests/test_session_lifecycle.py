from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend import db, engine, life, seed


def _reset_sessions() -> None:
    engine.SESSIONS.clear()
    closed_order = getattr(engine, "_CLOSED_SESSION_ORDER", None)
    if closed_order is not None:
        closed_order.clear()


@pytest.fixture(autouse=True)
def reset_sessions() -> None:
    _reset_sessions()
    yield
    _reset_sessions()


@pytest.fixture
def session_id(isolated_db: Path) -> str:
    seed.seed()
    return engine.start_session(db.CHILD_ID)["session_id"]


def test_close_session_keeps_minimal_tombstone_and_reuses_result(
    session_id: str,
) -> None:
    active = engine.get_session(session_id)
    expected = {"diary": {"id": 7}, "moment": {"status": "skipped"}}
    calls = []

    def finalize(session: dict) -> dict:
        calls.append(session)
        return expected

    first = engine.close_session(session_id, finalize)
    second = engine.close_session(
        session_id,
        lambda _session: pytest.fail("a closed session must not finalize twice"),
    )

    assert first is expected
    assert second is expected
    assert calls == [active]
    assert engine.get_session(session_id) is None
    assert engine.SESSIONS[session_id] == {"closed": True, "result": expected}
    assert isinstance(engine._session_lock(session_id), type(threading.RLock()))


def test_active_session_rehydrates_history_state_and_gemini_handle(
    session_id: str,
) -> None:
    engine.record_voice_user(session_id, "我喜欢恐龙")
    engine.record_voice_doll(session_id, "我也记住啦")
    assert engine.claim_opening(session_id) is True
    assert engine.update_gemini_resumption_handle(session_id, "handle-1") is True

    engine.SESSIONS.clear()

    restored = engine.get_session(session_id)
    assert restored is not None
    assert restored["session_id"] == session_id
    assert restored["history"] == [
        {"role": "user", "content": "我喜欢恐龙"},
        {"role": "assistant", "content": "我也记住啦"},
    ]
    assert restored["opening_sent"] is True
    assert restored["gemini_resumption_handle"] == "handle-1"
    assert engine.get_session_history(session_id) == restored["history"]
    assert engine.claim_opening(session_id) is False


def test_closed_session_rejects_late_transcript_and_idle_writes(
    session_id: str,
) -> None:
    engine.record_voice_user(session_id, "关闭前")
    result = engine.close_session(session_id, lambda _session: {"ok": True})
    session_db_id = db.q1("SELECT id FROM sessions ORDER BY id DESC LIMIT 1")["id"]
    before = db.q1(
        "SELECT transcript_json FROM sessions WHERE id=?", (session_db_id,)
    )["transcript_json"]

    assert engine.record_voice_user(session_id, "关闭后的孩子消息") is None
    assert engine.record_voice_doll(session_id, "关闭后的玩偶消息") is None
    assert engine.claim_idle_nudge(session_id) is None

    after = db.q1(
        "SELECT transcript_json FROM sessions WHERE id=?", (session_db_id,)
    )["transcript_json"]
    assert json.loads(after) == json.loads(before)
    assert engine.SESSIONS[session_id] == {"closed": True, "result": result}


def test_close_exception_freezes_session_and_allows_retry(
    session_id: str,
) -> None:
    engine.record_voice_user(session_id, "关闭前")
    session_db_id = engine.SESSIONS[session_id]["db_id"]
    before = db.q1(
        "SELECT transcript_json FROM sessions WHERE id=?", (session_db_id,)
    )["transcript_json"]

    def fail(_session: dict) -> dict:
        raise RuntimeError("finalize failed")

    with pytest.raises(RuntimeError, match="finalize failed"):
        engine.close_session(session_id, fail)

    assert engine.get_session(session_id) is None
    assert engine.record_voice_user(session_id, "失败后的迟到消息") is None
    assert engine.record_voice_doll(session_id, "失败后的迟到回复") is None
    assert db.q1(
        "SELECT transcript_json FROM sessions WHERE id=?", (session_db_id,)
    )["transcript_json"] == before

    expected = {"ok": True}
    assert engine.close_session(session_id, lambda session: expected) is expected
    assert engine.get_session(session_id) is None


def test_closed_tombstones_are_bounded_without_evicting_active_sessions(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed.seed()
    monkeypatch.setattr(engine, "CLOSED_SESSION_LIMIT", 2)
    active_id = engine.start_session(db.CHILD_ID)["session_id"]
    closed_ids = [
        engine.start_session(db.CHILD_ID)["session_id"] for _ in range(4)
    ]

    for closed_id in closed_ids:
        engine.close_session(closed_id, lambda _session, value=closed_id: value)

    assert engine.get_session(active_id) is not None
    assert active_id in engine.SESSIONS
    assert closed_ids[0] not in engine.SESSIONS
    assert closed_ids[1] not in engine.SESSIONS
    assert engine.SESSIONS[closed_ids[2]] == {
        "closed": True,
        "result": closed_ids[2],
    }
    assert engine.SESSIONS[closed_ids[3]] == {
        "closed": True,
        "result": closed_ids[3],
    }
    assert sum(
        1 for session in engine.SESSIONS.values() if session.get("closed") is True
    ) == 2


def test_private_arc_advances_once_only_after_confirmed_choice(
    isolated_db: Path,
) -> None:
    seed.seed()
    before = db.q1(
        "SELECT id,current_beat FROM doll_arcs "
        "WHERE child_id=? AND status='active' ORDER BY id LIMIT 1",
        (db.CHILD_ID,),
    )

    life.life_tick(
        db.CHILD_ID,
        now=datetime(2026, 7, 11, 1, 0, tzinfo=timezone.utc),
        timezone="Asia/Shanghai",
    )
    life.life_tick(
        db.CHILD_ID,
        now=datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc),
        timezone="Asia/Shanghai",
    )
    assert db.q1("SELECT current_beat FROM doll_arcs WHERE id=?", (before["id"],)) == {
        "current_beat": before["current_beat"]
    }

    session_id = engine.start_session(db.CHILD_ID)["session_id"]
    engine.record_voice_user(session_id, "今天风很大")
    assert db.q1("SELECT current_beat FROM doll_arcs WHERE id=?", (before["id"],)) == {
        "current_beat": before["current_beat"]
    }

    session = engine.get_session(session_id)
    session["pending_choice"] = True
    engine.record_voice_user(session_id, "我选橡果味蛋糕")
    assert db.q1("SELECT current_beat FROM doll_arcs WHERE id=?", (before["id"],)) == {
        "current_beat": before["current_beat"] + 1
    }

    engine.record_voice_user(session_id, "还要加一颗樱桃")
    assert db.q1("SELECT current_beat FROM doll_arcs WHERE id=?", (before["id"],)) == {
        "current_beat": before["current_beat"] + 1
    }
