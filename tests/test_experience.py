from __future__ import annotations

import importlib
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend import db, media


def _experience_module():
    assert importlib.util.find_spec("backend.experience") is not None, (
        "backend.experience is not implemented"
    )
    return importlib.import_module("backend.experience")


@pytest.fixture
def clock() -> list[datetime]:
    return [datetime(2026, 7, 11, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))]


@pytest.fixture
def experience_service(isolated_db: Path, clock: list[datetime]):
    experience = _experience_module()
    return experience.ExperienceService(
        catalog=media.default_catalog(reload=True),
        now_fn=lambda: clock[0],
        timezone="Asia/Shanghai",
        generation_delay_seconds=3,
    )


def _settle(
    service,
    source_id: str = "42",
    event_key: str = "canon_choice",
    payload: dict | None = None,
) -> dict:
    return service.settle_candidate(
        1,
        "session",
        source_id,
        event_key,
        payload if payload is not None else {"choice": "橡果味"},
    )


def _publish(service, clock: list[datetime], settled: dict) -> dict:
    clock[0] += timedelta(seconds=4)
    return service.refresh_moment(settled["moment_id"])


def test_insignificant_candidate_creates_nothing(experience_service) -> None:
    result = _settle(experience_service, payload={"choice": "", "meaningful": False})
    assert result == {"status": "skipped", "reason": "insignificant"}
    assert db.q1("SELECT COUNT(*) AS n FROM moments") == {"n": 0}
    assert db.q1("SELECT COUNT(*) AS n FROM generation_jobs") == {"n": 0}


def test_candidate_requires_exact_asset_match(experience_service) -> None:
    result = _settle(experience_service, payload={"choice": "蜂蜜味"})
    assert result == {"status": "skipped", "reason": "no_matching_asset"}
    assert db.q1("SELECT COUNT(*) AS n FROM moments") == {"n": 0}


def test_unsafe_candidate_does_not_consume_quota(experience_service) -> None:
    result = _settle(experience_service, payload={"choice": "橡果味", "safe": False})
    assert result == {"status": "skipped", "reason": "unsafe"}
    assert db.q1("SELECT COUNT(*) AS n FROM moments") == {"n": 0}


def test_duplicate_settlement_returns_same_moment(experience_service) -> None:
    first = _settle(experience_service)
    second = _settle(experience_service)
    assert first["moment_id"] == second["moment_id"]
    assert first["job_id"] == second["job_id"]
    assert first["created"] is True
    assert second["created"] is False
    assert db.q1("SELECT COUNT(*) AS n FROM moments") == {"n": 1}


def test_settlement_rolls_back_if_job_creation_fails(
    experience_service, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_submit(*args, **kwargs):
        raise RuntimeError("job insert failed")

    monkeypatch.setattr(experience_service.provider, "submit", fail_submit)
    with pytest.raises(RuntimeError, match="job insert failed"):
        _settle(experience_service)
    assert db.q1("SELECT COUNT(*) AS n FROM moments") == {"n": 0}
    assert db.q1("SELECT COUNT(*) AS n FROM generation_jobs") == {"n": 0}


def test_daily_quota_counts_rendering_and_published(experience_service) -> None:
    created = [_settle(experience_service, source_id=str(i)) for i in range(3)]
    blocked = _settle(experience_service, source_id="fourth")
    assert all(item["status"] == "rendering" for item in created)
    assert blocked == {"status": "skipped", "reason": "daily_quota"}
    assert db.q1("SELECT COUNT(*) AS n FROM moments") == {"n": 3}


def test_failed_moment_releases_quota_after_at_most_two_attempts(
    experience_service,
) -> None:
    first = _settle(experience_service, source_id="first")
    _settle(experience_service, source_id="second")
    _settle(experience_service, source_id="third")
    first_job = db.q1(
        "SELECT id FROM generation_jobs WHERE moment_id=? ORDER BY attempt DESC LIMIT 1",
        (first["moment_id"],),
    )
    db.execute(
        "UPDATE generation_jobs SET status='failed', error_code='asset_error' WHERE id=?",
        (first_job["id"],),
    )
    retrying = experience_service.refresh_moment(first["moment_id"])
    assert retrying["status"] == "rendering"
    assert retrying["attempt"] == 2

    second_job = db.q1(
        "SELECT id FROM generation_jobs WHERE moment_id=? ORDER BY attempt DESC LIMIT 1",
        (first["moment_id"],),
    )
    db.execute(
        "UPDATE generation_jobs SET status='failed', error_code='asset_error' WHERE id=?",
        (second_job["id"],),
    )
    failed = experience_service.refresh_moment(first["moment_id"])
    assert failed["status"] == "failed"
    assert db.q1(
        "SELECT COUNT(*) AS n FROM generation_jobs WHERE moment_id=?",
        (first["moment_id"],),
    ) == {"n": 2}

    replacement = _settle(experience_service, source_id="replacement")
    assert replacement["status"] == "rendering"


@pytest.mark.parametrize(
    ("result_error", "error_code"),
    [
        (media.MediaNotFound("asset vanished"), "not_found"),
        (media.MediaNotReady("provider result not ready"), "not_ready"),
        (media.MediaError("provider transport failed"), "media_error"),
    ],
)
def test_result_media_errors_retry_then_release_quota(
    experience_service,
    clock: list[datetime],
    monkeypatch: pytest.MonkeyPatch,
    result_error: media.MediaError,
    error_code: str,
) -> None:
    first = _settle(experience_service, source_id="first")
    _settle(experience_service, source_id="second")
    _settle(experience_service, source_id="third")

    def fail_result(job_id: int) -> dict:
        raise result_error

    monkeypatch.setattr(experience_service.provider, "result", fail_result)
    clock[0] += timedelta(seconds=4)

    retrying = experience_service.refresh_moment(first["moment_id"])
    assert retrying["status"] == "rendering"
    assert retrying["attempt"] == 2
    assert db.q1(
        "SELECT status,error_code FROM generation_jobs "
        "WHERE moment_id=? AND attempt=1",
        (first["moment_id"],),
    ) == {"status": "failed", "error_code": error_code}

    clock[0] += timedelta(seconds=4)
    failed = experience_service.refresh_moment(first["moment_id"])
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == error_code
    assert db.q1(
        "SELECT status,error_code FROM moments WHERE id=?",
        (first["moment_id"],),
    ) == {"status": "failed", "error_code": error_code}
    assert db.q1(
        "SELECT COUNT(*) AS n FROM generation_jobs WHERE moment_id=?",
        (first["moment_id"],),
    ) == {"n": 2}

    replacement = _settle(experience_service, source_id="replacement")
    assert replacement["status"] == "rendering"


def test_stale_failed_poll_cannot_fail_a_concurrently_queued_retry(
    experience_service, monkeypatch: pytest.MonkeyPatch
) -> None:
    settled = _settle(experience_service, source_id="retry-race")
    moment = db.q1("SELECT * FROM moments WHERE id=?", (settled["moment_id"],))
    failed_job = db.q1(
        "SELECT * FROM generation_jobs WHERE moment_id=? AND attempt=1",
        (settled["moment_id"],),
    )
    db.execute(
        "UPDATE generation_jobs SET status='failed',error_code='asset_error' WHERE id=?",
        (failed_job["id"],),
    )
    failed_job["status"] = "failed"
    failed_job["error_code"] = "asset_error"

    def poll_while_other_request_queues_retry(job_id: int) -> str:
        assert job_id == failed_job["id"]
        experience_service._start_retry(moment, failed_job)
        return "failed"

    monkeypatch.setattr(
        experience_service.provider, "poll", poll_while_other_request_queues_retry
    )
    result = experience_service.refresh_moment(settled["moment_id"])

    assert result["status"] == "rendering"
    assert result["attempt"] == 2
    assert db.q1(
        "SELECT status FROM moments WHERE id=?", (settled["moment_id"],)
    ) == {"status": "rendering"}
    assert db.q1(
        "SELECT attempt,status FROM generation_jobs WHERE moment_id=? "
        "ORDER BY attempt DESC LIMIT 1",
        (settled["moment_id"],),
    ) == {"attempt": 2, "status": "queued"}


def test_ready_job_publishes_after_service_restart(
    isolated_db: Path, clock: list[datetime]
) -> None:
    experience = _experience_module()
    catalog = media.default_catalog(reload=True)
    before_restart = experience.ExperienceService(
        catalog=catalog,
        now_fn=lambda: clock[0],
        timezone="Asia/Shanghai",
        generation_delay_seconds=3,
    )
    settled = _settle(before_restart)
    clock[0] += timedelta(seconds=4)

    after_restart = experience.ExperienceService(
        catalog=catalog,
        now_fn=lambda: clock[0],
        timezone="Asia/Shanghai",
        generation_delay_seconds=3,
    )
    published = after_restart.refresh_moment(settled["moment_id"])
    assert published["status"] == "published"
    assert published["media"]["src"].startswith("/demo-media/")
    row = db.q1("SELECT status,published_asset_id FROM moments WHERE id=?", (settled["moment_id"],))
    assert row == {"status": "published", "published_asset_id": "choice-cake-v1"}


def test_published_asset_and_story_are_immutable(
    experience_service, clock: list[datetime]
) -> None:
    settled = _settle(experience_service)
    published = _publish(experience_service, clock, settled)
    original = db.q1(
        "SELECT title,story,published_asset_id,published_at FROM moments WHERE id=?",
        (settled["moment_id"],),
    )
    db.execute(
        "UPDATE generation_jobs SET asset_id='hill-wind-a' WHERE moment_id=?",
        (settled["moment_id"],),
    )
    again = experience_service.refresh_moment(settled["moment_id"])
    assert again["status"] == "published"
    assert db.q1(
        "SELECT title,story,published_asset_id,published_at FROM moments WHERE id=?",
        (settled["moment_id"],),
    ) == original
    assert published["media"] == again["media"]


def test_feed_separates_pending_and_hides_failed(
    experience_service, clock: list[datetime]
) -> None:
    published = _settle(experience_service, source_id="published")
    pending = _settle(experience_service, source_id="pending")
    failed = _settle(experience_service, source_id="failed")
    _publish(experience_service, clock, published)
    db.execute("UPDATE moments SET status='failed' WHERE id=?", (failed["moment_id"],))

    feed = experience_service.personal_feed(1)
    assert [item["id"] for item in feed["items"]] == [published["moment_id"]]
    assert [item["id"] for item in feed["pending"]] == [pending["moment_id"]]
    assert failed["moment_id"] not in {
        item["id"] for group in feed.values() for item in group
    }


def test_publishing_creates_keepsake_but_does_not_auto_collect(
    experience_service, clock: list[datetime]
) -> None:
    settled = _settle(experience_service)
    published = _publish(experience_service, clock, settled)
    assert published["keepsake"]["name"] == "橡果餐布"
    assert published["keepsake"]["collected"] is False
    assert experience_service.pocket(1) == {"items": []}


def test_pocket_membership_is_idempotent_and_uncollect_keeps_row(
    experience_service, clock: list[datetime]
) -> None:
    settled = _settle(experience_service)
    published = _publish(experience_service, clock, settled)
    keepsake_id = published["keepsake"]["id"]

    first = experience_service.set_pocket(1, keepsake_id, True)
    timestamps = db.q1(
        "SELECT collected_at,updated_at FROM pocket_entries "
        "WHERE child_id=? AND keepsake_id=?",
        (1, keepsake_id),
    )
    clock[0] += timedelta(hours=1)
    second = experience_service.set_pocket(1, keepsake_id, True)
    assert first["collected"] is True
    assert second["collected"] is True
    assert second["updated_at"] == first["updated_at"]
    assert db.q1(
        "SELECT collected_at,updated_at FROM pocket_entries "
        "WHERE child_id=? AND keepsake_id=?",
        (1, keepsake_id),
    ) == timestamps
    assert len(experience_service.pocket(1)["items"]) == 1

    removed = experience_service.set_pocket(1, keepsake_id, False)
    assert removed["collected"] is False
    assert experience_service.pocket(1) == {"items": []}
    assert db.q1(
        "SELECT collected FROM pocket_entries WHERE child_id=? AND keepsake_id=?",
        (1, keepsake_id),
    ) == {"collected": 0}
