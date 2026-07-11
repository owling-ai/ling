"""Versioned demo media catalog and deterministic timestamp-driven provider."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

from . import db


ROOT = Path(__file__).resolve().parent
DEFAULT_WORLD_PATH = ROOT / "demo" / "base_world.json"
DEFAULT_ASSETS_PATH = ROOT / "demo" / "mock_assets.json"
DEFAULT_MEDIA_ROOT = ROOT / "demo_media"
MEANINGFUL_EVENT_KEYS = {"word_taught", "canon_choice", "story_beat", "growth_change"}
KEEPSAKE_APPEARANCES = {"amber", "clay", "pea", "blue"}


class ManifestError(ValueError):
    pass


class MediaError(RuntimeError):
    code = "media_error"


class MediaNotReady(MediaError):
    code = "not_ready"


class MediaGenerationFailed(MediaError):
    code = "generation_failed"


class MediaNotFound(MediaError):
    code = "not_found"


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"invalid manifest {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ManifestError(f"invalid manifest {path.name}: object required")
    if payload.get("schema_version") != 1:
        raise ManifestError(f"unsupported schema_version in {path.name}")
    return payload


def _positive_int(value, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ManifestError(f"{field} must be a positive integer")
    return value


def _local_file(media_root: Path, value: str, kind: str) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ManifestError(f"invalid {kind} path")
    root = media_root.resolve()
    resolved = (root / value).resolve()
    if root not in resolved.parents:
        raise ManifestError(f"invalid {kind} path")
    if not resolved.is_file():
        raise ManifestError(f"missing {kind}: {value}")
    return resolved


def _validate_checksum(path: Path, expected: str, kind: str) -> None:
    if not isinstance(expected, str) or len(expected) != 64:
        raise ManifestError(f"invalid {kind} checksum")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected.lower():
        raise ManifestError(f"checksum mismatch for {kind}: {path.name}")


def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hour, minute = (int(part) for part in value.split(":", 1))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ManifestError(f"invalid schedule time: {value!r}") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ManifestError(f"invalid schedule time: {value!r}")
    return hour, minute


def _validate_meaningful_moment(asset_id: str, asset: dict) -> None:
    moment = asset.get("moment")
    if not isinstance(moment, dict):
        raise ManifestError(f"asset {asset_id} requires moment")
    for field in ("title", "story"):
        if not isinstance(moment.get(field), str) or not moment[field].strip():
            raise ManifestError(f"asset {asset_id} requires moment.{field}")
    if "keepsake" not in moment:
        raise ManifestError(f"asset {asset_id} requires moment.keepsake")
    keepsake = moment["keepsake"]
    if keepsake is None:
        return
    if not isinstance(keepsake, dict):
        raise ManifestError(f"asset {asset_id} has invalid keepsake")
    for field in ("name", "description", "appearance"):
        if not isinstance(keepsake.get(field), str) or not keepsake[field].strip():
            raise ManifestError(f"asset {asset_id} requires keepsake.{field}")
    if keepsake["appearance"] not in KEEPSAKE_APPEARANCES:
        raise ManifestError(f"asset {asset_id} has invalid keepsake.appearance")
    image_url = keepsake.get("image_url")
    if image_url is not None and not isinstance(image_url, str):
        raise ManifestError(f"asset {asset_id} has invalid keepsake.image_url")


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt_timezone.utc)


def _iso(value: datetime) -> str:
    return _as_aware(value).isoformat(timespec="seconds")


def _from_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return _as_aware(parsed)


class MediaCatalog:
    def __init__(self, world: dict, assets: list[dict], media_root: Path):
        self.world = world
        self.assets = assets
        self.media_root = media_root
        self._assets_by_id = {asset["asset_id"]: asset for asset in assets}
        self._events = {
            (event["event_id"], event["event_version"]): event
            for event in world["events"]
        }

    def asset(self, asset_id: str) -> dict:
        try:
            return self._assets_by_id[asset_id]
        except KeyError as exc:
            raise MediaNotFound(f"asset not found: {asset_id}") from exc

    def matching_assets(
        self,
        event_key: str,
        event_value: str,
        semantic_version: int,
        allowed_asset_groups: list[str] | None = None,
    ) -> list[dict]:
        allowed = set(allowed_asset_groups or [])
        matches = [
            asset
            for asset in self.assets
            if asset["event_key"] == event_key
            and asset["event_value"] == event_value
            and asset["semantic_version"] == semantic_version
            and (not allowed or asset["asset_group"] in allowed)
        ]
        return sorted(matches, key=lambda asset: asset["asset_id"])

    def select_asset(
        self,
        event_key: str,
        event_value: str,
        semantic_version: int,
        stable_key: str,
        allowed_asset_groups: list[str] | None = None,
    ) -> dict:
        matches = self.matching_assets(
            event_key, event_value, semantic_version, allowed_asset_groups
        )
        if not matches:
            raise MediaNotFound(
                f"no exact asset for {event_key}:{event_value}:v{semantic_version}"
            )
        digest = hashlib.sha256(stable_key.encode("utf-8")).digest()
        return matches[int.from_bytes(digest[:8], "big") % len(matches)]

    def select_variant(self, doll_id: str, event_id: str, event_version: int) -> dict:
        return self.select_asset(
            "base_world",
            event_id,
            event_version,
            f"{doll_id}:{event_id}:{event_version}",
        )

    def select_world_event(
        self, doll_id: str, now: datetime, timezone: str
    ) -> dict:
        try:
            zone = ZoneInfo(timezone)
        except Exception as exc:
            raise ManifestError(f"invalid timezone: {timezone}") from exc
        local_now = _as_aware(now).astimezone(zone)
        minute_of_day = local_now.hour * 60 + local_now.minute
        selected = None
        for slot in self.world["schedule"]:
            start_h, start_m = _parse_hhmm(slot["start"])
            end_h, end_m = _parse_hhmm(slot["end"])
            start = start_h * 60 + start_m
            end = end_h * 60 + end_m
            inside = start <= minute_of_day < end if start < end else (
                minute_of_day >= start or minute_of_day < end
            )
            if inside:
                selected = slot
                break
        if selected is None:
            raise ManifestError("world schedule does not cover the current time")

        event_key = (selected["event_id"], selected["event_version"])
        event = dict(self._events[event_key])
        asset = self.select_variant(doll_id, *event_key)
        end_h, end_m = _parse_hhmm(selected["end"])
        next_transition = local_now.replace(
            hour=end_h, minute=end_m, second=0, microsecond=0
        )
        if next_transition <= local_now:
            next_transition += timedelta(days=1)
        event["variant_id"] = asset["asset_id"]
        event["media"] = self.public_asset(asset)
        return {
            "mode": selected["mode"],
            "timezone": timezone,
            "next_transition_at": next_transition.isoformat(timespec="seconds"),
            "event": event,
        }

    @staticmethod
    def public_asset(asset: dict) -> dict:
        def public_uri(value: str) -> str:
            if value.startswith("/") or "://" in value:
                return value
            return f"/demo-media/{value}"

        return {
            "kind": asset["media_kind"],
            "src": public_uri(asset["src"]),
            "poster": public_uri(asset["poster"]),
            "mime_type": asset["mime_type"],
            "width": asset["width"],
            "height": asset["height"],
            "duration_ms": asset["duration_ms"],
            "alt": asset["alt"],
        }


def asset_snapshot(asset: dict, *, provider: str) -> dict:
    """Freeze every field needed to replay an already published render."""
    provenance = asset.get("provenance")
    if not isinstance(provenance, dict):
        provenance = {}
    return {
        "asset_id": asset["asset_id"],
        "media": MediaCatalog.public_asset(asset),
        "sha256": dict(asset.get("sha256") or {}),
        "provenance": {
            **provenance,
            "provider": provider,
            "asset_group": asset["asset_group"],
            "semantic_version": asset["semantic_version"],
        },
    }


def load_manifests(
    world_path: str | Path = DEFAULT_WORLD_PATH,
    assets_path: str | Path = DEFAULT_ASSETS_PATH,
    media_root: str | Path = DEFAULT_MEDIA_ROOT,
) -> MediaCatalog:
    world_path = Path(world_path)
    assets_path = Path(assets_path)
    media_root = Path(media_root)
    world = _read_json(world_path)
    asset_payload = _read_json(assets_path)

    events = world.get("events")
    schedule = world.get("schedule")
    assets = asset_payload.get("assets")
    if not isinstance(events, list) or not events:
        raise ManifestError("base world requires events")
    if not isinstance(schedule, list) or not schedule:
        raise ManifestError("base world requires schedule")
    if not isinstance(assets, list) or not assets:
        raise ManifestError("asset manifest requires assets")

    event_ids: set[tuple[str, int]] = set()
    for event in events:
        try:
            key = (event["event_id"], _positive_int(event["event_version"], "event_version"))
            asset_group = event["asset_group"]
        except (KeyError, TypeError) as exc:
            raise ManifestError("malformed base world event") from exc
        if key in event_ids:
            raise ManifestError(f"duplicate event id/version: {key}")
        event_ids.add(key)
        if not all(isinstance(event.get(field), str) and event[field] for field in ("title", "summary")):
            raise ManifestError(f"event {key} requires title and summary")
        if not isinstance(asset_group, str) or not asset_group:
            raise ManifestError(f"event {key} requires asset_group")
        if not isinstance(event.get("timeline", []), list):
            raise ManifestError(f"event {key} has invalid timeline")

    for slot in schedule:
        try:
            _parse_hhmm(slot["start"])
            _parse_hhmm(slot["end"])
            key = (slot["event_id"], slot["event_version"])
        except (KeyError, TypeError) as exc:
            raise ManifestError("malformed schedule slot") from exc
        if slot.get("mode") not in {"day", "night", "sleeping"}:
            raise ManifestError("invalid schedule mode")
        if key not in event_ids:
            raise ManifestError(f"schedule references unknown event: {key}")

    seen_asset_ids: set[str] = set()
    for asset in assets:
        try:
            asset_id = asset["asset_id"]
            event_key = asset["event_key"]
            asset_group = asset["asset_group"]
            semantic_version = _positive_int(asset["semantic_version"], "semantic_version")
            width = _positive_int(asset["width"], "width")
            height = _positive_int(asset["height"], "height")
            _positive_int(asset["duration_ms"], "duration_ms")
        except (KeyError, TypeError) as exc:
            raise ManifestError("malformed asset") from exc
        if not isinstance(asset_id, str) or not asset_id:
            raise ManifestError("asset_id must be a non-empty string")
        if asset_id in seen_asset_ids:
            raise ManifestError(f"duplicate asset_id: {asset_id}")
        seen_asset_ids.add(asset_id)
        if event_key != "base_world" and event_key not in MEANINGFUL_EVENT_KEYS:
            raise ManifestError(f"invalid event_key: {event_key}")
        if event_key in MEANINGFUL_EVENT_KEYS:
            _validate_meaningful_moment(asset_id, asset)
        if not isinstance(asset.get("event_value"), str) or not asset["event_value"]:
            raise ManifestError(f"asset {asset_id} requires event_value")
        if not isinstance(asset_group, str) or not asset_group:
            raise ManifestError(f"asset {asset_id} requires asset_group")
        if asset.get("media_kind") != "video" or asset.get("mime_type") != "video/mp4":
            raise ManifestError(f"asset {asset_id} must be video/mp4")
        if width >= height:
            raise ManifestError(f"asset {asset_id} must be portrait-oriented")
        if not isinstance(asset.get("alt"), str) or not asset["alt"].strip():
            raise ManifestError(f"asset {asset_id} requires alt text")
        media_path = _local_file(media_root, asset.get("src"), "media")
        poster_path = _local_file(media_root, asset.get("poster"), "poster")
        checksums = asset.get("sha256")
        if not isinstance(checksums, dict):
            raise ManifestError(f"asset {asset_id} requires checksums")
        _validate_checksum(media_path, checksums.get("media"), "media")
        _validate_checksum(poster_path, checksums.get("poster"), "poster")
        asset["semantic_version"] = semantic_version

    for event in events:
        if not any(
            asset["event_key"] == "base_world"
            and asset["event_value"] == event["event_id"]
            and asset["semantic_version"] == event["event_version"]
            and asset["asset_group"] == event["asset_group"]
            for asset in assets
        ):
            raise ManifestError(f'event {event["event_id"]} has no matching media')

    return MediaCatalog(world, assets, media_root)


_DEFAULT_CATALOG: MediaCatalog | None = None


def default_catalog(*, reload: bool = False) -> MediaCatalog:
    global _DEFAULT_CATALOG
    if reload or _DEFAULT_CATALOG is None:
        _DEFAULT_CATALOG = load_manifests()
    return _DEFAULT_CATALOG


def select_world_event(doll_id: str, now: datetime, timezone: str) -> dict:
    return default_catalog().select_world_event(doll_id, now, timezone)


class GenerationProvider(Protocol):
    name: str

    def submit(self, request: dict, *, conn=None) -> int: ...

    def poll(self, job_id: int) -> str: ...

    def result(self, job_id: int) -> dict: ...


class MockMediaProvider:
    name = "mock"

    def __init__(
        self,
        catalog: MediaCatalog | None = None,
        *,
        now_fn: Callable[[], datetime] | None = None,
        delay_seconds: int = 3,
    ):
        self.catalog = catalog or default_catalog()
        self.now_fn = now_fn or (lambda: datetime.now(dt_timezone.utc))
        self.delay_seconds = delay_seconds

    def submit(self, request: dict, *, conn=None) -> int:
        if conn is None:
            existing = db.q1(
                "SELECT id FROM generation_jobs WHERE idempotency_key=?",
                (request["idempotency_key"],),
            )
        else:
            row = conn.execute(
                "SELECT id FROM generation_jobs WHERE idempotency_key=?",
                (request["idempotency_key"],),
            ).fetchone()
            existing = dict(row) if row else None
        if existing:
            return existing["id"]
        asset = self.catalog.select_asset(
            request["event_key"],
            request["event_value"],
            request["semantic_version"],
            request["idempotency_key"],
            request.get("allowed_asset_groups"),
        )
        now = _as_aware(self.now_fn())
        ready_at = now + timedelta(seconds=self.delay_seconds)
        sql = (
            "INSERT INTO generation_jobs("
            "moment_id,attempt,media_kind,provider,asset_group,status,asset_id,idempotency_key,"
            "created_at,ready_at,updated_at) VALUES(?,?,?,?,?,'queued',?,?,?,?,?)"
        )
        params = (
            request["moment_id"],
            request.get("attempt", 1),
            request["media_kind"],
            self.name,
            asset["asset_group"],
            asset["asset_id"],
            request["idempotency_key"],
            _iso(now),
            _iso(ready_at),
            _iso(now),
        )
        if conn is None:
            return db.execute(sql, params)
        return conn.execute(sql, params).lastrowid

    def poll(self, job_id: int) -> str:
        row = db.q1("SELECT * FROM generation_jobs WHERE id=?", (job_id,))
        if not row:
            raise MediaNotFound(f"job not found: {job_id}")
        if row["status"] in {"succeeded", "failed"}:
            return row["status"]
        now = _as_aware(self.now_fn())
        created_at = _from_iso(row["created_at"])
        ready_at = _from_iso(row["ready_at"])
        if now >= ready_at:
            status = "succeeded"
        elif now > created_at:
            status = "running"
        else:
            status = "queued"
        if status != row["status"]:
            if status == "succeeded":
                db.execute(
                    "UPDATE generation_jobs SET status=?,updated_at=? WHERE id=? "
                    "AND status IN ('queued','running')",
                    (status, _iso(now), job_id),
                )
            elif status == "running":
                db.execute(
                    "UPDATE generation_jobs SET status=?,updated_at=? WHERE id=? "
                    "AND status='queued'",
                    (status, _iso(now), job_id),
                )
        final = db.q1("SELECT status FROM generation_jobs WHERE id=?", (job_id,))
        if not final:
            raise MediaNotFound(f"job not found: {job_id}")
        return final["status"]

    def result(self, job_id: int) -> dict:
        status = self.poll(job_id)
        row = db.q1("SELECT * FROM generation_jobs WHERE id=?", (job_id,))
        if status == "failed":
            raise MediaGenerationFailed(row.get("error_code") or "generation_failed")
        if status != "succeeded":
            raise MediaNotReady(f"job {job_id} is {status}")
        return self.catalog.asset(row["asset_id"])
