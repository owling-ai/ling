from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend import db, experience, jimeng_video, media, media_worker


VALID_MP4 = b"\x00\x00\x00\x18ftypmp42" + b"generated-video"
VALID_PNG = b"\x89PNG\r\n\x1a\n" + b"generated-poster"


class FakeArkClient:
    def __init__(self):
        self.created: list[dict] = []
        self.queries: list[str] = []
        self.downloads: list[str] = []
        self.create_error: Exception | None = None
        self.task_response: dict = {
            "id": "task-123",
            "status": "running",
        }

    def create_task(self, payload: dict) -> dict:
        self.created.append(payload)
        if self.create_error:
            error, self.create_error = self.create_error, None
            raise error
        return {"id": "task-123"}

    def get_task(self, task_id: str) -> dict:
        self.queries.append(task_id)
        return self.task_response

    def download(self, url: str, destination: Path, max_bytes: int) -> str:
        self.downloads.append(url)
        if url.endswith(".mp4"):
            destination.write_bytes(VALID_MP4)
            return "video/mp4"
        destination.write_bytes(VALID_PNG)
        return "image/png"


@pytest.fixture
def clock() -> list[datetime]:
    return [datetime(2026, 7, 11, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))]


@pytest.fixture
def ark_setup(isolated_db: Path, tmp_path: Path, clock: list[datetime]):
    catalog = media.default_catalog(reload=True)
    client = FakeArkClient()
    provider = jimeng_video.JimengArkProvider(
        catalog,
        client=client,
        now_fn=lambda: clock[0],
        storage_root=tmp_path / "generated",
        reference_image_url="https://assets.example.test/ling-reference.png",
        poll_seconds=2,
        task_timeout_seconds=60,
        max_provider_failures=3,
        max_download_bytes=1024 * 1024,
    )
    service = experience.ExperienceService(
        catalog=catalog,
        provider=provider,
        now_fn=lambda: clock[0],
        timezone="Asia/Shanghai",
    )
    return service, provider, client


def _settle(service: experience.ExperienceService, source_id: str = "ark-1") -> dict:
    return service.settle_candidate(
        1,
        "demo",
        source_id,
        "canon_choice",
        {"choice": "橡果味"},
    )


def test_generation_job_schema_has_recovery_fields(isolated_db: Path) -> None:
    columns = {
        row["name"] for row in db.q("PRAGMA table_info(generation_jobs)")
    }
    assert {
        "external_task_id",
        "request_json",
        "provider_response_json",
        "next_poll_at",
        "provider_failures",
        "media_path",
        "poster_path",
        "media_sha256",
        "poster_sha256",
        "completed_at",
    } <= columns


def test_requested_jimeng_without_key_degrades_to_mock(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LING_MEDIA_PROVIDER", "jimeng")
    monkeypatch.delenv("LING_ARK_VIDEO_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    provider = jimeng_video.configured_provider(media.default_catalog(reload=True))
    mode = jimeng_video.provider_mode_info()

    assert provider.name == "mock"
    assert mode == {
        "requested_provider": "jimeng",
        "active_provider": "mock",
        "api_key_configured": False,
        "degraded": True,
        "degraded_reason": "missing_ark_api_key",
    }


def test_requested_jimeng_with_key_enables_ark_without_network(
    isolated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LING_MEDIA_PROVIDER", "seedance")
    monkeypatch.setenv("LING_ARK_VIDEO_API_KEY", "test-only-key")
    monkeypatch.delenv("ARK_API_KEY", raising=False)

    provider = jimeng_video.configured_provider(media.default_catalog(reload=True))
    mode = jimeng_video.provider_mode_info()

    assert provider.name == "jimeng-ark"
    assert mode["active_provider"] == "jimeng-ark"
    assert mode["api_key_configured"] is True
    assert mode["degraded"] is False


def test_existing_generation_job_table_migrates_before_new_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = getattr(db._local, "conn", None)
    if current is not None:
        current.close()
        delattr(db._local, "conn")
    path = tmp_path / "legacy.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE generation_jobs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,moment_id INTEGER NOT NULL,"
        "attempt INTEGER NOT NULL,media_kind TEXT NOT NULL,provider TEXT NOT NULL,"
        "asset_group TEXT NOT NULL,status TEXT NOT NULL,asset_id TEXT,"
        "idempotency_key TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,"
        "ready_at TEXT NOT NULL,updated_at TEXT NOT NULL,error_code TEXT DEFAULT '',"
        "UNIQUE(moment_id,attempt))"
    )
    connection.commit()
    connection.close()
    monkeypatch.setattr(db, "DB_PATH", str(path))

    db.init_db()

    columns = {
        row["name"] for row in db.q("PRAGMA table_info(generation_jobs)")
    }
    assert "external_task_id" in columns
    assert "next_poll_at" in columns
    indexes = {
        row["name"] for row in db.q("PRAGMA index_list(generation_jobs)")
    }
    assert "idx_generation_jobs_provider_due" in indexes


def test_submit_persists_request_without_network(ark_setup) -> None:
    service, _, client = ark_setup
    settled = _settle(service)

    assert settled["status"] == "rendering"
    assert client.created == []
    job = db.q1("SELECT * FROM generation_jobs WHERE id=?", (settled["job_id"],))
    request = json.loads(job["request_json"])
    assert job["provider"] == "jimeng-ark"
    assert job["status"] == "queued"
    assert request["template_asset_id"] == "choice-cake-v1"
    assert "9:16" in request["prompt"]
    assert "橡果" in request["prompt"]
    assert "api_key" not in job["request_json"].lower()


def test_job_restarts_reuse_frozen_config_and_remote_task(
    ark_setup, clock: list[datetime]
) -> None:
    service, provider, _ = ark_setup
    settled = _settle(service, "restart-recovery")

    submit_client = FakeArkClient()
    restarted_provider = jimeng_video.JimengArkProvider(
        provider.catalog,
        client=submit_client,
        now_fn=lambda: clock[0],
        storage_root=provider.storage_root,
        model="replacement-model",
        reference_image_url="https://assets.example.test/replacement.png",
        poll_seconds=2,
    )
    restarted_service = experience.ExperienceService(
        catalog=provider.catalog,
        provider=restarted_provider,
        now_fn=lambda: clock[0],
        timezone="Asia/Shanghai",
    )

    media_worker.MediaGenerationWorker(restarted_service).run_once()

    assert submit_client.created[0]["model"] == provider.model
    assert submit_client.created[0]["content"][1]["image_url"]["url"] == (
        "https://assets.example.test/ling-reference.png"
    )

    completion_client = FakeArkClient()
    completion_client.task_response = {
        "id": "task-123",
        "status": "succeeded",
        "model": provider.model,
        "content": {
            "video_url": "https://output.example.test/task-123.mp4",
            "last_frame_url": "https://output.example.test/task-123.png",
        },
    }
    clock[0] += timedelta(seconds=3)
    completion_provider = jimeng_video.JimengArkProvider(
        provider.catalog,
        client=completion_client,
        now_fn=lambda: clock[0],
        storage_root=provider.storage_root,
        model="another-replacement-model",
        reference_image_url="",
        poll_seconds=2,
    )
    completion_service = experience.ExperienceService(
        catalog=provider.catalog,
        provider=completion_provider,
        now_fn=lambda: clock[0],
        timezone="Asia/Shanghai",
    )

    media_worker.MediaGenerationWorker(completion_service).run_once()

    assert completion_client.created == []
    assert completion_client.queries == ["task-123"]
    detail = completion_service.moment_detail(settled["moment_id"])
    assert detail["status"] == "published"
    snapshot = json.loads(
        db.q1(
            "SELECT published_asset_json FROM moments WHERE id=?",
            (settled["moment_id"],),
        )["published_asset_json"]
    )
    assert snapshot["provenance"]["model"] == provider.model


def test_worker_submits_polls_downloads_and_publishes_local_asset(
    ark_setup, clock: list[datetime]
) -> None:
    service, provider, client = ark_setup
    settled = _settle(service)
    worker = media_worker.MediaGenerationWorker(service, interval_seconds=1)

    first = worker.run_once()
    assert first["processed"] == 1
    assert client.created[0]["model"] == provider.model
    assert client.created[0]["ratio"] == "9:16"
    assert client.created[0]["duration"] == 6
    assert client.created[0]["return_last_frame"] is True
    assert client.created[0]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "https://assets.example.test/ling-reference.png"},
        "role": "reference_image",
    }
    job = db.q1("SELECT * FROM generation_jobs WHERE id=?", (settled["job_id"],))
    assert job["status"] == "running"
    assert job["external_task_id"] == "task-123"

    client.task_response = {
        "id": "task-123",
        "status": "succeeded",
        "model": provider.model,
        "content": {
            "video_url": "https://output.example.test/task-123.mp4",
            "last_frame_url": "https://output.example.test/task-123.png",
            "width": 720,
            "height": 1280,
            "duration": 6,
        },
    }
    clock[0] += timedelta(seconds=3)
    second = worker.run_once()
    assert second["processed"] == 1
    assert client.downloads == [
        "https://output.example.test/task-123.mp4",
        "https://output.example.test/task-123.png",
    ]

    detail = service.moment_detail(settled["moment_id"])
    assert detail["status"] == "published"
    assert detail["media"]["src"].startswith("/generated-media/job-")
    assert detail["media"]["poster"].startswith("/generated-media/job-")
    job = db.q1("SELECT * FROM generation_jobs WHERE id=?", (settled["job_id"],))
    video_path = provider.storage_root / job["media_path"]
    poster_path = provider.storage_root / job["poster_path"]
    assert video_path.read_bytes() == VALID_MP4
    assert poster_path.read_bytes() == VALID_PNG
    assert not list(provider.storage_root.glob("*.part"))
    snapshot = json.loads(
        db.q1(
            "SELECT published_asset_json FROM moments WHERE id=?",
            (settled["moment_id"],),
        )["published_asset_json"]
    )
    assert snapshot["provenance"]["external_task_id"] == "task-123"
    assert "video_url" not in snapshot["provenance"]


def test_transient_create_error_is_backed_off_without_failing_moment(
    ark_setup, clock: list[datetime]
) -> None:
    service, provider, client = ark_setup
    settled = _settle(service, "transient")
    client.create_error = jimeng_video.ArkRequestError(
        "busy", status=503, retryable=True
    )

    assert provider.poll(settled["job_id"]) == "queued"
    row = db.q1(
        "SELECT status,provider_failures,error_code,next_poll_at "
        "FROM generation_jobs WHERE id=?",
        (settled["job_id"],),
    )
    assert row["status"] == "queued"
    assert row["provider_failures"] == 1
    assert row["error_code"] == "503"

    clock[0] += timedelta(seconds=5)
    assert provider.poll(settled["job_id"]) == "running"
    assert len(client.created) == 2
    assert service.moment_detail(settled["moment_id"])["status"] == "rendering"


def test_non_retryable_create_error_fails_and_queues_one_retry(
    ark_setup, clock: list[datetime]
) -> None:
    service, _, client = ark_setup
    settled = _settle(service, "unauthorized")
    client.create_error = jimeng_video.ArkRequestError(
        "unauthorized", status=401, retryable=False
    )

    refreshed = service.refresh_moment(settled["moment_id"])
    assert refreshed["status"] == "rendering"
    assert refreshed["attempt"] == 2
    jobs = db.q(
        "SELECT attempt,status,request_json FROM generation_jobs "
        "WHERE moment_id=? ORDER BY attempt",
        (settled["moment_id"],),
    )
    assert [(job["attempt"], job["status"]) for job in jobs] == [
        (1, "failed"),
        (2, "queued"),
    ]
    assert json.loads(jobs[1]["request_json"])["prompt"] == json.loads(
        jobs[0]["request_json"]
    )["prompt"]


def test_generated_video_uses_catalog_poster_when_last_frame_is_missing(
    ark_setup, clock: list[datetime]
) -> None:
    service, provider, client = ark_setup
    settled = _settle(service, "fallback-poster")
    assert provider.poll(settled["job_id"]) == "running"
    client.task_response = {
        "id": "task-123",
        "status": "succeeded",
        "content": {"video_url": "https://output.example.test/task-123.mp4"},
    }
    clock[0] += timedelta(seconds=3)
    assert provider.poll(settled["job_id"]) == "succeeded"
    asset = provider.result(settled["job_id"])
    assert asset["src"].startswith("/generated-media/")
    assert asset["poster"] == "/demo-media/choice-cake.png"
    assert asset["sha256"]["poster"] == provider.catalog.asset(
        "choice-cake-v1"
    )["sha256"]["poster"]


def test_jimeng_service_routes_existing_mock_job_to_mock_provider(
    ark_setup, clock: list[datetime]
) -> None:
    service, _, _ = ark_setup
    moment_id = db.execute(
        "INSERT INTO moments("
        "child_id,source_type,source_id,event_key,event_value,semantic_version,"
        "idempotency_key,local_date,title,story,status,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,'rendering',?)",
        (
            1,
            "demo",
            "legacy-mock",
            "canon_choice",
            "橡果味",
            1,
            "legacy-mock-moment",
            "2026-07-11",
            "生日蛋糕有答案啦",
            "你选了橡果味。",
            clock[0].isoformat(timespec="seconds"),
        ),
    )
    mock = service._providers["mock"]
    mock.submit(
        {
            "moment_id": moment_id,
            "attempt": 1,
            "media_kind": "video",
            "event_key": "canon_choice",
            "event_value": "橡果味",
            "semantic_version": 1,
            "idempotency_key": "legacy-mock-job",
            "allowed_asset_groups": ["moment-choice-cake"],
        }
    )

    clock[0] += timedelta(seconds=4)
    detail = service.refresh_moment(moment_id)

    assert detail["status"] == "published"
    assert detail["media"]["src"] == "/demo-media/choice-cake.mp4"
    assert db.q1(
        "SELECT provider,status FROM generation_jobs WHERE moment_id=?", (moment_id,)
    ) == {"provider": "mock", "status": "succeeded"}
