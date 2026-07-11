from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend import db, engine, experience, llm, media, realtime


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOT = ROOT / "frontend"
FORBIDDEN_SOURCE_PATHS = (
    "/api/facts",
    "/api/diary",
    "/api/mastery",
    "/api/report",
    "/api/state",
    "/api/admin",
    "/api/volcengine",
)


@pytest.fixture
def client(isolated_db: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(llm, "worker_live", lambda: False)
    engine.SESSIONS.clear()
    experience._DEFAULT_SERVICE = None
    from backend.app import app

    with TestClient(
        app,
        base_url="http://127.0.0.1:8888",
        follow_redirects=False,
        client=("127.0.0.1", 50000),
    ) as test_client:
        yield test_client
    engine.SESSIONS.clear()
    experience._DEFAULT_SERVICE = None


def assert_content_type(response, expected_prefix: str) -> None:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith(expected_prefix)


def test_child_and_parent_entrypoints_redirect_to_canonical_scope(client: TestClient) -> None:
    for app_name in ("child", "parent"):
        redirect = client.get(f"/{app_name}")
        assert redirect.status_code in {307, 308}
        assert redirect.headers["location"].endswith(f"/{app_name}/")
        assert_content_type(client.get(f"/{app_name}/"), "text/html")


def test_retired_design_prototype_is_not_served(client: TestClient) -> None:
    assert client.get("/design").status_code == 404
    assert client.head("/design").status_code == 404


def test_pwa_manifests_service_workers_and_icons_are_served(client: TestClient) -> None:
    for app_name in ("child", "parent"):
        manifest_response = client.get(f"/{app_name}/manifest.webmanifest")
        assert_content_type(manifest_response, "application/manifest+json")
        manifest = manifest_response.json()
        assert manifest["display"] == "standalone"
        assert manifest["id"] == f"/{app_name}/"
        assert manifest["start_url"] == f"/{app_name}/"
        assert manifest["scope"] == f"/{app_name}/"

        sw_response = client.get(f"/{app_name}/sw.js")
        assert_content_type(sw_response, "text/javascript")
        assert "/api/" in sw_response.text

        for icon in manifest["icons"]:
            icon_url = urljoin(f"/{app_name}/", icon["src"])
            icon_response = client.get(icon_url)
            assert_content_type(icon_response, "image/png")


def test_manifest_media_urls_exist_without_network(client: TestClient) -> None:
    catalog = media.default_catalog(reload=True)
    media_urls = {
        f'/demo-media/{asset["src"]}'
        for asset in catalog.assets
    } | {
        f'/demo-media/{asset["poster"]}'
        for asset in catalog.assets
    }

    assert media_urls
    for url in sorted(media_urls):
        response = client.get(url)
        assert response.status_code == 200, url
        assert response.headers["content-type"].startswith(("video/", "image/"))


def test_mobile_app_source_does_not_request_legacy_or_admin_apis() -> None:
    source_text = "\n".join(
        path.read_text(encoding="utf-8")
        for app_dir in (FRONTEND_ROOT / "child", FRONTEND_ROOT / "parent")
        for path in app_dir.glob("*.mjs")
    )
    for forbidden in FORBIDDEN_SOURCE_PATHS:
        assert forbidden not in source_text


def test_parent_projection_guard_has_all_forbidden_internal_fields() -> None:
    model_source = (FRONTEND_ROOT / "parent" / "model.mjs").read_text(encoding="utf-8")
    for forbidden in (
        "transcript",
        "quote",
        "session_id",
        "prompt",
        "provider",
        "job",
        "successes",
        "exposures",
        "due_date",
        "private_canon",
        "delete_url",
    ):
        assert json.dumps(forbidden) in model_source


def test_api_responses_are_private_and_never_cached(client: TestClient) -> None:
    for path in (
        "/api/child/world/now",
        "/api/parent/today",
        "/api/moments/999999",
        "/api/not-a-real-route",
    ):
        response = client.get(path)
        directives = {
            item.strip() for item in response.headers.get("cache-control", "").split(",")
        }
        assert {"private", "no-store"}.issubset(directives), path


def test_remote_debug_and_admin_apis_require_a_token(
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LING_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("LING_ALLOW_UNAUTHENTICATED", raising=False)
    from backend.app import app

    with TestClient(
        app,
        follow_redirects=False,
        client=("203.0.113.10", 50000),
    ) as remote:
        for method, path in (
            (remote.get, "/api/facts"),
            (remote.get, "/api/state"),
            (remote.post, "/api/session/start"),
            (remote.post, "/api/session/end"),
            (remote.post, "/api/volcengine/prepare"),
            (remote.post, "/api/admin/reseed"),
        ):
            response = method(path)
            assert response.status_code == 403, path
            assert response.headers["cache-control"] == "private, no-store"

        assert remote.get("/api/child/feed").status_code == 200
        assert remote.get("/api/parent/today").status_code == 200


def test_remote_debug_api_accepts_configured_bearer_token(
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LING_ADMIN_TOKEN", "demo-test-token")
    monkeypatch.delenv("LING_ALLOW_UNAUTHENTICATED", raising=False)
    from backend.app import app

    with TestClient(
        app,
        follow_redirects=False,
        client=("203.0.113.10", 50000),
        headers={"Authorization": "Bearer demo-test-token"},
    ) as remote:
        assert remote.get("/api/facts").status_code == 200
        response = remote.post("/api/session/start")

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"session_id", "opening", "review_items"}
    assert "memory_pack" not in payload


def test_hackathon_mode_allows_public_debug_api_without_token(
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LING_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("LING_ALLOW_UNAUTHENTICATED", "1")
    from backend.app import app

    with TestClient(
        app,
        base_url="https://public-demo.example",
        follow_redirects=False,
        client=("203.0.113.10", 50000),
    ) as public_client:
        assert public_client.get("/api/state").status_code == 200
        assert public_client.post("/api/session/start").status_code == 200


def test_legacy_console_consumes_sanitized_session_start_shape() -> None:
    source = (FRONTEND_ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "start.review_items" in source
    assert "start.memory_pack" not in source


def test_legacy_console_supports_preselected_video_and_minicpm_mode_switching() -> None:
    source = (FRONTEND_ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "let videoRequested = false" in source
    assert "button.disabled = !supported || RT.videoSwitching" in source
    assert 'query.set("video", videoMode ? "1" : "0")' in source
    assert "restartMinicpmTransport()" in source
    assert "if (!RT.on) return;" in source
    assert "if (videoRequested && !await startVideo()) videoRequested = false" in source
    assert 'speechStarted && RT.provider === "minicpm"' in source


def test_remote_realtime_websocket_requires_debug_access(
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LING_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("LING_ALLOW_UNAUTHENTICATED", raising=False)
    from backend.app import app

    with TestClient(app, client=("203.0.113.10", 50000)) as remote:
        with pytest.raises(WebSocketDisconnect) as denied:
            with remote.websocket_connect(
                "/api/realtime/ws?session_id=private&provider=gemini"
            ):
                pass

    assert denied.value.code == 1008


def test_remote_realtime_websocket_accepts_configured_token(
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LING_ADMIN_TOKEN", "demo-test-token")
    monkeypatch.delenv("LING_ALLOW_UNAUTHENTICATED", raising=False)

    async def fake_bridge(
        ws, session_id: str, provider: str | None, video: bool = False
    ) -> None:
        await ws.accept()
        await ws.send_json(
            {"session_id": session_id, "provider": provider, "video": video}
        )
        await ws.close()

    monkeypatch.setattr(realtime, "bridge", fake_bridge)
    from backend.app import app

    with TestClient(
        app,
        client=("203.0.113.10", 50000),
        headers={"Authorization": "Bearer demo-test-token"},
    ) as remote:
        with remote.websocket_connect(
            "/api/realtime/ws?session_id=private&provider=minicpm&video=1"
        ) as socket:
            assert socket.receive_json() == {
                "session_id": "private",
                "provider": "minicpm",
                "video": True,
            }


def test_hackathon_mode_allows_public_realtime_websocket_without_token(
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LING_ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("LING_ALLOW_UNAUTHENTICATED", "1")

    async def fake_bridge(
        ws,
        session_id: str,
        provider: str | None,
        video: bool = False,
    ) -> None:
        await ws.accept()
        await ws.send_json({"session_id": session_id, "provider": provider})
        await ws.close()

    monkeypatch.setattr(realtime, "bridge", fake_bridge)
    from backend.app import app

    with TestClient(
        app,
        base_url="https://public-demo.example",
        client=("203.0.113.10", 50000),
    ) as public_client:
        with public_client.websocket_connect(
            "/api/realtime/ws?session_id=private&provider=gemini"
        ) as socket:
            assert socket.receive_json() == {
                "session_id": "private",
                "provider": "gemini",
            }


def test_api_internal_errors_are_private_and_never_cached(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenExperience:
        def child_world_now(self, _child_id: int):
            raise RuntimeError("private internal detail")

    monkeypatch.setattr(experience, "default_service", lambda **_kwargs: BrokenExperience())

    response = client.get("/api/child/world/now")

    assert response.status_code == 500
    assert response.headers["cache-control"] == "private, no-store"
    assert "private internal detail" not in response.text


def test_legacy_console_does_not_offer_per_fact_deletion() -> None:
    source = (FRONTEND_ROOT / "assets" / "app.js").read_text(encoding="utf-8")

    assert "api.del" not in source
    assert 'class="del"' not in source
    assert "/facts/${" not in source


def test_loopback_reverse_proxy_is_not_treated_as_a_local_request(
    isolated_db: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LING_ADMIN_TOKEN", raising=False)
    from backend.app import app

    with TestClient(
        app,
        base_url="https://mm.liaoxingyi.com",
        client=("127.0.0.1", 50000),
        headers={"X-Forwarded-For": "203.0.113.10"},
    ) as proxied:
        response = proxied.get("/api/facts")

    assert response.status_code == 403
    assert response.headers["cache-control"] == "private, no-store"


def test_legacy_per_fact_delete_is_not_routed(client: TestClient) -> None:
    assert client.delete("/api/facts/1").status_code in {404, 405}


def test_demo_runner_opens_hackathon_network_by_default() -> None:
    runner = (ROOT / "run.sh").read_text(encoding="utf-8")
    assert 'host="${LING_HOST:-0.0.0.0}"' in runner
    assert 'LING_ALLOW_UNAUTHENTICATED="${LING_ALLOW_UNAUTHENTICATED:-1}"' in runner
