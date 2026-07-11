from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend import db, life, memory, seed


def test_life_tick_projects_global_world_without_reading_private_memory(
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed.seed()

    def private_access(*_args, **_kwargs):
        pytest.fail("global world tick must not access child-private storage")

    monkeypatch.setattr(memory, "get_card", private_access)
    monkeypatch.setattr(memory, "list_diary", private_access)
    monkeypatch.setattr(db, "q", private_access)
    monkeypatch.setattr(db, "q1", private_access)
    monkeypatch.setattr(db, "execute", private_access)

    result = life.life_tick(
        db.CHILD_ID,
        now=datetime(2026, 7, 11, 9, 0, tzinfo=timezone.utc),
        timezone="Asia/Shanghai",
    )

    assert result["mode"] == "day"
    assert result["event_id"] == "hill-wind"
    assert result["event_version"] == 1
    assert result["text"] == "灵灵带着积木风筝去等今天第一阵风。"
    assert result["media"]["src"].startswith("/demo-media/")


def test_private_arc_only_advances_through_explicit_interaction(
    isolated_db: Path,
) -> None:
    seed.seed()
    before = db.q1(
        "SELECT id,current_beat,status FROM doll_arcs "
        "WHERE child_id=? AND status='active'",
        (db.CHILD_ID,),
    )

    first = life.advance_private_arc(db.CHILD_ID)
    second = life.advance_private_arc(db.CHILD_ID)

    assert before["current_beat"] == 3
    assert first == {"arc_id": before["id"], "current_beat": 4, "status": "active"}
    assert second == {"arc_id": before["id"], "current_beat": 5, "status": "done"}
    assert life.advance_private_arc(db.CHILD_ID) is None


def test_private_choice_commits_canon_arc_and_event_atomically(
    isolated_db: Path,
) -> None:
    seed.seed()
    event = db.q1(
        "SELECT id,child_reaction FROM doll_events WHERE child_id=? "
        "AND share_status='unshared' ORDER BY id DESC LIMIT 1",
        (db.CHILD_ID,),
    )
    arc = db.q1(
        "SELECT id,current_beat FROM doll_arcs WHERE child_id=? AND status='active'",
        (db.CHILD_ID,),
    )
    source_key = f"session:42:event:{event['id']}"
    conn = db.get_conn()
    conn.execute(
        "CREATE TRIGGER abort_private_choice BEFORE UPDATE OF child_reaction "
        "ON doll_events WHEN NEW.id=%d BEGIN "
        "SELECT RAISE(ABORT, 'injected event failure'); END" % event["id"]
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError, match="injected event failure"):
        life.commit_private_choice(
            db.CHILD_ID,
            source_key=source_key,
            event_id=event["id"],
            entity="生日蛋糕",
            fact_text="悠悠决定：橡果味",
            child_reaction="橡果味蛋糕",
        )

    assert db.q1("SELECT current_beat FROM doll_arcs WHERE id=?", (arc["id"],)) == {
        "current_beat": arc["current_beat"]
    }
    assert db.q1(
        "SELECT COUNT(*) AS n FROM doll_canon WHERE source_key=?", (source_key,)
    ) == {"n": 0}
    assert db.q1("SELECT child_reaction FROM doll_events WHERE id=?", (event["id"],)) == {
        "child_reaction": event["child_reaction"]
    }

    conn.execute("DROP TRIGGER abort_private_choice")
    conn.commit()
    first = life.commit_private_choice(
        db.CHILD_ID,
        source_key=source_key,
        event_id=event["id"],
        entity="生日蛋糕",
        fact_text="悠悠决定：橡果味",
        child_reaction="橡果味蛋糕",
    )
    second = life.commit_private_choice(
        db.CHILD_ID,
        source_key=source_key,
        event_id=event["id"],
        entity="生日蛋糕",
        fact_text="悠悠决定：橡果味",
        child_reaction="橡果味蛋糕",
    )

    assert first["created"] is True
    assert second["created"] is False
    assert db.q1("SELECT current_beat FROM doll_arcs WHERE id=?", (arc["id"],)) == {
        "current_beat": arc["current_beat"] + 1
    }
    assert db.q1(
        "SELECT COUNT(*) AS n FROM doll_canon WHERE source_key=?", (source_key,)
    ) == {"n": 1}
    assert db.q1("SELECT child_reaction FROM doll_events WHERE id=?", (event["id"],)) == {
        "child_reaction": "橡果味蛋糕"
    }
