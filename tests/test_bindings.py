from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import db, engine, experience, llm


DEMO_PAYLOAD = "ling://bind/LING-DEMO-2026"
DEMO_SHORT_CODE = "LING-DEMO-2026"
CHILD_INSTALLATION = "child-installation-001"
PARENT_INSTALLATION = "parent-installation-001"


@pytest.fixture
def client(isolated_db: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm, "worker_live", lambda: False)
    monkeypatch.setenv("LING_MEDIA_PROVIDER", "mock")
    monkeypatch.delenv("LING_DEMO_BINDING_CODE", raising=False)
    engine.SESSIONS.clear()
    experience._DEFAULT_SERVICE = None
    from backend.app import app

    with TestClient(app) as test_client:
        yield test_client
    engine.SESSIONS.clear()
    experience._DEFAULT_SERVICE = None


def test_demo_qr_is_registered_and_served_as_png(client: TestClient) -> None:
    response = client.get("/api/demo/binding-qr.png")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/png")
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert client.get("/api/state").json()["binding_demo"] == {
        "short_code": DEMO_SHORT_CODE,
        "qr_url": "/api/demo/binding-qr.png",
    }
    registered = db.q1(
        "SELECT label,enabled,length(token_hash) AS hash_length "
        "FROM binding_qr_codes"
    )
    assert registered == {
        "label": "hackathon-demo",
        "enabled": 1,
        "hash_length": 64,
    }


def test_binding_rejects_unknown_qr_and_parent_first(client: TestClient) -> None:
    invalid = client.post(
        "/api/bindings/child-scan",
        json={
            "qr_token": "LING-NOT-REGISTERED",
            "installation_id": CHILD_INSTALLATION,
        },
    )
    parent_first = client.post(
        "/api/bindings/parent-scan",
        json={
            "qr_token": DEMO_PAYLOAD,
            "installation_id": PARENT_INSTALLATION,
        },
    )

    assert invalid.status_code == 400
    assert "未登记" in invalid.json()["detail"]
    assert parent_first.status_code == 409
    assert "孩子端" in parent_first.json()["detail"]
    assert db.q1("SELECT COUNT(*) AS n FROM app_bindings") == {"n": 0}


def test_child_then_parent_binding_is_persistent_and_idempotent(
    client: TestClient,
) -> None:
    child_first = client.post(
        "/api/bindings/child-scan",
        json={
            "qr_token": DEMO_PAYLOAD,
            "installation_id": CHILD_INSTALLATION,
        },
    )
    child_repeat = client.post(
        "/api/bindings/child-scan",
        json={
            "qr_token": DEMO_SHORT_CODE,
            "installation_id": CHILD_INSTALLATION,
        },
    )

    assert child_first.status_code == 200
    assert child_first.json()["status"] == "pending"
    assert child_repeat.status_code == 200
    assert child_repeat.json()["binding_id"] == child_first.json()["binding_id"]
    pending = client.get(
        "/api/bindings/status",
        params={"installation_id": CHILD_INSTALLATION},
    )
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"

    parent_first = client.post(
        "/api/bindings/parent-scan",
        json={
            "qr_token": DEMO_SHORT_CODE,
            "installation_id": PARENT_INSTALLATION,
        },
    )
    parent_repeat = client.post(
        "/api/bindings/parent-scan",
        json={
            "qr_token": DEMO_PAYLOAD,
            "installation_id": PARENT_INSTALLATION,
        },
    )

    assert parent_first.status_code == 200
    payload = parent_first.json()
    assert payload["status"] == "active"
    assert payload["child_installation_id"] == CHILD_INSTALLATION
    assert payload["parent_installation_id"] == PARENT_INSTALLATION
    assert payload["child_name"]
    assert payload["doll_name"]
    assert parent_repeat.status_code == 200
    assert parent_repeat.json() == payload

    polled = client.get(
        "/api/bindings/status",
        params={"installation_id": CHILD_INSTALLATION},
    )
    assert polled.status_code == 200
    assert polled.json() == payload
    assert db.q1(
        "SELECT status,child_installation_id,parent_installation_id "
        "FROM app_bindings"
    ) == {
        "status": "active",
        "child_installation_id": CHILD_INSTALLATION,
        "parent_installation_id": PARENT_INSTALLATION,
    }


def test_binding_conflicts_do_not_replace_installations(client: TestClient) -> None:
    child = client.post(
        "/api/bindings/child-scan",
        json={
            "qr_token": DEMO_PAYLOAD,
            "installation_id": CHILD_INSTALLATION,
        },
    )
    assert child.status_code == 200

    another_child = client.post(
        "/api/bindings/child-scan",
        json={
            "qr_token": DEMO_PAYLOAD,
            "installation_id": "child-installation-002",
        },
    )
    same_phone_parent = client.post(
        "/api/bindings/parent-scan",
        json={
            "qr_token": DEMO_PAYLOAD,
            "installation_id": CHILD_INSTALLATION,
        },
    )
    assert another_child.status_code == 409
    assert same_phone_parent.status_code == 409
    assert "另一台手机" in same_phone_parent.json()["detail"]

    active = client.post(
        "/api/bindings/parent-scan",
        json={
            "qr_token": DEMO_PAYLOAD,
            "installation_id": PARENT_INSTALLATION,
        },
    )
    another_parent = client.post(
        "/api/bindings/parent-scan",
        json={
            "qr_token": DEMO_PAYLOAD,
            "installation_id": "parent-installation-002",
        },
    )
    assert active.status_code == 200
    assert another_parent.status_code == 409
    assert db.q1(
        "SELECT child_installation_id,parent_installation_id FROM app_bindings"
    ) == {
        "child_installation_id": CHILD_INSTALLATION,
        "parent_installation_id": PARENT_INSTALLATION,
    }


def test_binding_status_returns_404_before_child_scan(client: TestClient) -> None:
    response = client.get(
        "/api/bindings/status",
        params={"installation_id": CHILD_INSTALLATION},
    )

    assert response.status_code == 404
    assert "还没有发起绑定" in response.json()["detail"]


def test_admin_reset_binding_returns_demo_to_issued(client: TestClient) -> None:
    assert client.post(
        "/api/bindings/child-scan",
        json={
            "qr_token": DEMO_PAYLOAD,
            "installation_id": CHILD_INSTALLATION,
        },
    ).status_code == 200
    assert client.post(
        "/api/bindings/parent-scan",
        json={
            "qr_token": DEMO_PAYLOAD,
            "installation_id": PARENT_INSTALLATION,
        },
    ).status_code == 200

    reset = client.post("/api/admin/reset-binding")

    assert reset.status_code == 200
    assert reset.json() == {
        "status": "issued",
        "deleted_bindings": 1,
        "short_code": DEMO_SHORT_CODE,
        "qr_payload": DEMO_PAYLOAD,
        "message": "Demo 绑定已重置，请从孩子端重新扫码",
    }
    assert client.get(
        "/api/bindings/status",
        params={"installation_id": CHILD_INSTALLATION},
    ).status_code == 404
    parent_first = client.post(
        "/api/bindings/parent-scan",
        json={
            "qr_token": DEMO_PAYLOAD,
            "installation_id": PARENT_INSTALLATION,
        },
    )
    assert parent_first.status_code == 409
