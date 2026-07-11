from __future__ import annotations

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
