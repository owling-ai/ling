from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import db, engine, experience, llm, memory, seed


@pytest.fixture
def client(isolated_db: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm, "worker_live", lambda: False)
    engine.SESSIONS.clear()
    experience._DEFAULT_SERVICE = None
    from backend.app import app

    with TestClient(app) as test_client:
        yield test_client
    engine.SESSIONS.clear()
    experience._DEFAULT_SERVICE = None


def test_mobile_apps_and_demo_media_are_served(client: TestClient) -> None:
    assert client.get("/child/").status_code == 200
    assert client.get("/parent/").status_code == 200
    media_response = client.get("/demo-media/hill-wind-a.mp4")
    assert media_response.status_code == 200
    assert media_response.headers["content-type"].startswith("video/mp4")


def test_child_and_parent_projection_routes(client: TestClient) -> None:
    child_world = client.get("/api/child/world/now")
    child_feed = client.get("/api/child/feed")
    assert child_world.status_code == 200
    assert child_feed.status_code == 200
    assert set(child_feed.json()) == {"items", "pending"}

    for path in (
        "/api/parent/today",
        "/api/parent/growth?period=week",
        "/api/parent/memory?limit=20",
        "/api/parent/guardian",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)


def test_admin_demo_moment_and_polling_route(client: TestClient) -> None:
    created = client.post(
        "/api/admin/demo-moment",
        json={
            "event_key": "canon_choice",
            "event_value": "橡果味",
            "source_id": "route-demo",
        },
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["status"] == "rendering"
    polled = client.get(f'/api/moments/{payload["moment_id"]}')
    assert polled.status_code == 200
    assert polled.json()["status"] in {"rendering", "published"}
    assert client.get("/api/moments/999999").status_code == 404


def test_pocket_route_is_idempotent(client: TestClient) -> None:
    pocket = client.get("/api/pocket")
    assert pocket.status_code == 200
    seeded = db.q1("SELECT id FROM keepsakes ORDER BY id LIMIT 1")
    assert seeded is not None
    first = client.put(f'/api/pocket/{seeded["id"]}', json={"collected": True})
    second = client.put(f'/api/pocket/{seeded["id"]}', json={"collected": True})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["collected"] is True
    assert second.json()["collected"] is True


def test_session_end_settles_canon_choice_idempotently(client: TestClient) -> None:
    started = client.post("/api/session/start")
    assert started.status_code == 200
    session_id = started.json()["session_id"]
    engine.SESSIONS[session_id]["canon_written"] = [
        {"entity": "生日蛋糕", "fact_text": "悠悠决定：橡果味"}
    ]

    first = client.post("/api/session/end", json={"session_id": session_id})
    second = client.post("/api/session/end", json={"session_id": session_id})
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["moment"]["moment_id"] == second.json()["moment"]["moment_id"]
    assert db.q1("SELECT COUNT(*) AS n FROM moments WHERE source_type='session'")["n"] >= 1


def test_experience_seed_backfill_is_idempotent_and_preserves_memory(
    isolated_db: Path,
) -> None:
    seed.seed()
    marker_id = memory.add_fact(1, "这条旧记忆不能被体验种子重置", "habit", "seed-marker")
    conn = db.get_conn()
    for table in ("pocket_entries", "keepsakes", "generation_jobs", "moments"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    facts_before = db.q1("SELECT COUNT(*) AS n FROM facts")["n"]

    seed.ensure_experience_seeded()
    seed.ensure_experience_seeded()

    assert db.q1("SELECT COUNT(*) AS n FROM facts") == {"n": facts_before}
    assert db.q1("SELECT text FROM facts WHERE id=?", (marker_id,)) == {
        "text": "这条旧记忆不能被体验种子重置"
    }
    assert db.q1("SELECT COUNT(*) AS n FROM moments") == {"n": 2}
    assert db.q1("SELECT COUNT(*) AS n FROM pocket_entries") == {"n": 1}
