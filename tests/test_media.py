from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend import db


EXPERIENCE_TABLES = {"moments", "generation_jobs", "keepsakes", "pocket_entries"}


def _media_module():
    assert importlib.util.find_spec("backend.media") is not None, "backend.media is not implemented"
    return importlib.import_module("backend.media")


def _table_names() -> set[str]:
    rows = db.q("SELECT name FROM sqlite_master WHERE type='table'")
    return {row["name"] for row in rows}


def _assert_experience_schema() -> None:
    missing = EXPERIENCE_TABLES - _table_names()
    assert not missing, f"missing experience tables: {sorted(missing)}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_catalog(tmp_path: Path, *, missing_media: bool = False) -> tuple[Path, Path, Path]:
    media_root = tmp_path / "media"
    media_root.mkdir()
    video = media_root / "hill-wind-a.mp4"
    poster = media_root / "hill-wind-a.png"
    video.write_bytes(b"fake-local-video")
    poster.write_bytes(b"fake-local-poster")

    base_world = {
        "schema_version": 1,
        "world_version": "2026-07-11",
        "timezone": "Asia/Shanghai",
        "events": [
            {
                "event_id": "hill-wind",
                "event_version": 1,
                "title": "去山坡等风",
                "summary": "灵灵带着积木风筝去等今天第一阵风。",
                "asset_group": "world-hill-wind",
                "timeline": [{"at": "08:30", "text": "风筝线绕好了"}],
            }
        ],
        "schedule": [
            {
                "slot_id": "day",
                "start": "06:00",
                "end": "18:00",
                "mode": "day",
                "event_id": "hill-wind",
                "event_version": 1,
            },
            {
                "slot_id": "night",
                "start": "18:00",
                "end": "21:00",
                "mode": "night",
                "event_id": "hill-wind",
                "event_version": 1,
            },
            {
                "slot_id": "sleeping",
                "start": "21:00",
                "end": "06:00",
                "mode": "sleeping",
                "event_id": "hill-wind",
                "event_version": 1,
            },
        ],
    }
    assets = {
        "schema_version": 1,
        "assets": [
            {
                "asset_id": "hill-wind-a",
                "media_kind": "video",
                "event_key": "base_world",
                "event_value": "hill-wind",
                "asset_group": "world-hill-wind",
                "semantic_version": 1,
                "src": "missing.mp4" if missing_media else video.name,
                "poster": poster.name,
                "mime_type": "video/mp4",
                "width": 720,
                "height": 900,
                "duration_ms": 4000,
                "alt": "灵灵在山坡上等风",
                "sha256": {
                    "media": _sha256(video),
                    "poster": _sha256(poster),
                },
            }
        ],
    }
    world_path = tmp_path / "base_world.json"
    assets_path = tmp_path / "mock_assets.json"
    world_path.write_text(json.dumps(base_world, ensure_ascii=False), encoding="utf-8")
    assets_path.write_text(json.dumps(assets, ensure_ascii=False), encoding="utf-8")
    return world_path, assets_path, media_root


def _insert_moment() -> int:
    return db.execute(
        "INSERT INTO moments("
        "child_id,source_type,source_id,event_key,event_value,semantic_version,idempotency_key,"
        "local_date,title,story,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            1,
            "session",
            "42",
            "word_taught",
            "kite",
            1,
            "moment:42:kite",
            "2026-07-11",
            "风筝终于飞起来啦",
            "悠悠教会灵灵 kite。",
            "rendering",
            "2026-07-11T10:00:00+08:00",
        ),
    )


def test_four_experience_tables_exist(isolated_db: Path) -> None:
    _assert_experience_schema()


def test_experience_uniqueness_constraints_reject_duplicates(isolated_db: Path) -> None:
    _assert_experience_schema()
    moment_id = _insert_moment()
    with pytest.raises(sqlite3.IntegrityError):
        _insert_moment()

    job_values = (
        moment_id,
        1,
        "video",
        "mock",
        "world-hill-wind",
        "queued",
        "hill-wind-a",
        "job:1",
        "2026-07-11T10:00:00+08:00",
        "2026-07-11T10:00:03+08:00",
        "2026-07-11T10:00:00+08:00",
    )
    sql = (
        "INSERT INTO generation_jobs("
        "moment_id,attempt,media_kind,provider,asset_group,status,asset_id,idempotency_key,"
        "created_at,ready_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)"
    )
    db.execute(sql, job_values)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (*job_values[:7], "job:other", *job_values[8:]))

    keepsake_id = db.execute(
        "INSERT INTO keepsakes(child_id,moment_id,name,description,appearance,image_url,created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (1, moment_id, "风筝牌牌", "第一次说出 kite", "amber", None, db.now()),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO keepsakes(child_id,moment_id,name,description,appearance,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (1, moment_id, "重复", "重复", "amber", db.now()),
        )

    db.execute(
        "INSERT INTO pocket_entries(child_id,keepsake_id,collected,collected_at,updated_at) "
        "VALUES(?,?,?,?,?)",
        (1, keepsake_id, 1, db.now(), db.now()),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO pocket_entries(child_id,keepsake_id,collected,updated_at) VALUES(?,?,?,?)",
            (1, keepsake_id, 0, db.now()),
        )


def test_transaction_rolls_back_on_exception(isolated_db: Path) -> None:
    _assert_experience_schema()
    assert hasattr(db, "transaction")
    with pytest.raises(RuntimeError):
        with db.transaction(immediate=True) as conn:
            conn.execute(
                "INSERT INTO moments("
                "child_id,source_type,source_id,event_key,event_value,semantic_version,idempotency_key,"
                "local_date,title,story,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (1, "session", "1", "word_taught", "kite", 1, "rollback", "2026-07-11", "t", "s", "rendering", db.now()),
            )
            raise RuntimeError("rollback")
    assert db.q1("SELECT id FROM moments WHERE idempotency_key='rollback'") is None


def test_manifest_rejects_duplicate_asset_ids(tmp_path: Path) -> None:
    media = _media_module()
    world_path, assets_path, media_root = _write_catalog(tmp_path)
    payload = json.loads(assets_path.read_text(encoding="utf-8"))
    payload["assets"].append(dict(payload["assets"][0]))
    assets_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(media.ManifestError, match="duplicate asset_id"):
        media.load_manifests(world_path, assets_path, media_root)


def test_manifest_rejects_malformed_schema_version(tmp_path: Path) -> None:
    media = _media_module()
    world_path, assets_path, media_root = _write_catalog(tmp_path)
    payload = json.loads(world_path.read_text(encoding="utf-8"))
    payload["schema_version"] = 99
    world_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(media.ManifestError, match="schema_version"):
        media.load_manifests(world_path, assets_path, media_root)


def test_manifest_rejects_missing_media(tmp_path: Path) -> None:
    media = _media_module()
    world_path, assets_path, media_root = _write_catalog(tmp_path, missing_media=True)
    with pytest.raises(media.ManifestError, match="missing media"):
        media.load_manifests(world_path, assets_path, media_root)


def test_variant_assignment_is_stable(tmp_path: Path) -> None:
    media = _media_module()
    world_path, assets_path, media_root = _write_catalog(tmp_path)
    catalog = media.load_manifests(world_path, assets_path, media_root)
    first = catalog.select_variant("ling-1", "hill-wind", 1)
    second = catalog.select_variant("ling-1", "hill-wind", 1)
    assert first["asset_id"] == second["asset_id"]


def test_world_selection_handles_overnight_slot(tmp_path: Path) -> None:
    media = _media_module()
    world_path, assets_path, media_root = _write_catalog(tmp_path)
    catalog = media.load_manifests(world_path, assets_path, media_root)
    now = datetime(2026, 7, 11, 23, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    selected = catalog.select_world_event("ling-1", now, "Asia/Shanghai")
    assert selected["mode"] == "sleeping"
    assert selected["event"]["event_id"] == "hill-wind"
    assert selected["next_transition_at"].endswith("+08:00")


def test_mock_provider_uses_persisted_ready_at(
    isolated_db: Path, tmp_path: Path
) -> None:
    media = _media_module()
    _assert_experience_schema()
    world_path, assets_path, media_root = _write_catalog(tmp_path)
    catalog = media.load_manifests(world_path, assets_path, media_root)
    clock = [datetime(2026, 7, 11, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))]
    provider = media.MockMediaProvider(catalog, now_fn=lambda: clock[0], delay_seconds=3)
    moment_id = _insert_moment()
    job_id = provider.submit(
        {
            "moment_id": moment_id,
            "media_kind": "video",
            "event_key": "base_world",
            "event_value": "hill-wind",
            "semantic_version": 1,
            "idempotency_key": "job:mock:1",
            "allowed_asset_groups": ["world-hill-wind"],
        }
    )
    assert provider.poll(job_id) == "queued"
    with pytest.raises(media.MediaNotReady):
        provider.result(job_id)

    row = db.q1("SELECT ready_at FROM generation_jobs WHERE id=?", (job_id,))
    assert row == {"ready_at": "2026-07-11T10:00:03+08:00"}
    clock[0] += timedelta(seconds=1)
    assert provider.poll(job_id) == "running"
    clock[0] += timedelta(seconds=3)
    assert provider.poll(job_id) == "succeeded"
    assert provider.result(job_id)["asset_id"] == "hill-wind-a"


def test_mock_provider_raises_typed_not_found(isolated_db: Path, tmp_path: Path) -> None:
    media = _media_module()
    world_path, assets_path, media_root = _write_catalog(tmp_path)
    provider = media.MockMediaProvider(media.load_manifests(world_path, assets_path, media_root))
    with pytest.raises(media.MediaNotFound):
        provider.poll(9999)


def test_mock_provider_raises_typed_generation_failed(
    isolated_db: Path, tmp_path: Path
) -> None:
    media = _media_module()
    _assert_experience_schema()
    world_path, assets_path, media_root = _write_catalog(tmp_path)
    provider = media.MockMediaProvider(media.load_manifests(world_path, assets_path, media_root))
    moment_id = _insert_moment()
    job_id = db.execute(
        "INSERT INTO generation_jobs("
        "moment_id,attempt,media_kind,provider,asset_group,status,asset_id,idempotency_key,"
        "created_at,ready_at,updated_at,error_code) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            moment_id,
            1,
            "video",
            "mock",
            "world-hill-wind",
            "failed",
            "hill-wind-a",
            "job:failed",
            db.now(),
            db.now(),
            db.now(),
            "missing_asset",
        ),
    )
    with pytest.raises(media.MediaGenerationFailed, match="missing_asset"):
        provider.result(job_id)
