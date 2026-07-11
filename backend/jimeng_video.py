"""Volcengine Ark / Seedance 2.0 asynchronous video generation provider."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Callable, Protocol

from . import db, media


DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_MODEL = "doubao-seedance-2-0-260128"
DEFAULT_STORAGE_ROOT = Path(__file__).resolve().parent.parent / "data" / "generated_media"
TERMINAL_STATUSES = {"succeeded", "failed"}
REMOTE_FAILED_STATUSES = {"failed", "expired", "cancelled"}
JIMENG_PROVIDER_ALIASES = {"jimeng", "jimeng-ark", "ark", "seedance"}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt_timezone.utc)


def _iso(value: datetime) -> str:
    return _aware(value).isoformat(timespec="seconds")


def _from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return _aware(datetime.fromisoformat(value))


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def generated_media_root() -> Path:
    configured = os.environ.get("LING_GENERATED_MEDIA_ROOT", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_STORAGE_ROOT


def _configured_api_key() -> str:
    return (
        os.environ.get("LING_ARK_VIDEO_API_KEY", "").strip()
        or os.environ.get("ARK_API_KEY", "").strip()
    )


def provider_mode_info() -> dict:
    requested = os.environ.get("LING_MEDIA_PROVIDER", "mock").strip().lower() or "mock"
    api_key_configured = bool(_configured_api_key())
    degraded = requested in JIMENG_PROVIDER_ALIASES and not api_key_configured
    return {
        "requested_provider": requested,
        "active_provider": "mock" if requested == "mock" or degraded else "jimeng-ark",
        "api_key_configured": api_key_configured,
        "degraded": degraded,
        "degraded_reason": "missing_ark_api_key" if degraded else None,
    }


class ArkRequestError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, retryable: bool = True):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class ArkClient(Protocol):
    def create_task(self, payload: dict) -> dict: ...

    def get_task(self, task_id: str) -> dict: ...

    def download(self, url: str, destination: Path, max_bytes: int) -> str: ...


class ArkHttpClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: int = 30,
        download_timeout_seconds: int = 180,
    ):
        if not api_key.strip():
            raise RuntimeError("ARK_API_KEY is required for Jimeng video generation")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.download_timeout_seconds = download_timeout_seconds

    def _json_request(
        self, method: str, path: str, payload: dict | None = None
    ) -> dict:
        body = None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=body, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            message = exc.read(4096).decode("utf-8", errors="replace")
            retryable = exc.code == 429 or exc.code >= 500
            raise ArkRequestError(
                f"Ark API HTTP {exc.code}: {message[:500]}",
                status=exc.code,
                retryable=retryable,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ArkRequestError(f"Ark API unavailable: {exc}") from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ArkRequestError("Ark API returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise ArkRequestError("Ark API returned a non-object response")
        return result

    def create_task(self, payload: dict) -> dict:
        return self._json_request("POST", "/contents/generations/tasks", payload)

    def get_task(self, task_id: str) -> dict:
        encoded = urllib.parse.quote(task_id, safe="")
        return self._json_request("GET", f"/contents/generations/tasks/{encoded}")

    def download(self, url: str, destination: Path, max_bytes: int) -> str:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ArkRequestError("Ark output URL must use HTTPS", retryable=False)
        request = urllib.request.Request(url, headers={"Accept": "*/*"})
        try:
            with urllib.request.urlopen(
                request, timeout=self.download_timeout_seconds
            ) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_bytes:
                    raise ArkRequestError(
                        "Ark output exceeds configured size limit", retryable=False
                    )
                content_type = response.headers.get_content_type()
                total = 0
                with destination.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > max_bytes:
                            raise ArkRequestError(
                                "Ark output exceeds configured size limit",
                                retryable=False,
                            )
                        output.write(chunk)
        except ArkRequestError:
            destination.unlink(missing_ok=True)
            raise
        except urllib.error.HTTPError as exc:
            destination.unlink(missing_ok=True)
            raise ArkRequestError(
                f"Ark output download HTTP {exc.code}",
                status=exc.code,
                retryable=exc.code == 429 or exc.code >= 500,
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            destination.unlink(missing_ok=True)
            raise ArkRequestError(f"Ark output download failed: {exc}") from exc
        return content_type


def _video_prompt(asset: dict, *, has_reference: bool) -> str:
    moment = asset.get("moment") or {}
    reference = (
        "严格保持图片1中灵灵的脸型、眼睛、毛色、围巾、胸灯和身体比例一致。"
        if has_reference
        else "保持灵灵作为圆润、柔软、可触摸的儿童陪伴玩偶，角色外观前后一致。"
    )
    story = str(moment.get("story") or asset.get("alt") or "").strip()
    return (
        f"{reference}高级手工针毡毛绒定格动画质感，细密柔软纤维，哑光材质。"
        f"场景事实：{asset['alt']}。故事背景：{story}。"
        "9:16 全屏竖屏，5到7秒，单一连续镜头，只发生一个清楚的小动作；"
        "灵灵和关键物件位于画面中下部，左上保留标题负空间，底部保留导航安全区。"
        "白天使用暖白、雾蓝、黏土粉、积木黄和豌豆绿；夜晚使用靛蓝和少量烛光金。"
        "无字幕、无界面、无文字、无Logo、无水印。避免角色漂移、眼睛变化、多余肢体、"
        "身体融合、快速运镜、突然转场和画面闪烁。"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_mp4(path: Path) -> None:
    with path.open("rb") as source:
        header = source.read(16)
    if len(header) < 12 or header[4:8] != b"ftyp":
        raise media.MediaGenerationFailed("generated output is not an MP4 file")


def _image_extension(path: Path) -> str | None:
    with path.open("rb") as source:
        header = source.read(16)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return ".webp"
    return None


def _safe_error_code(value: object, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "_", str(value or "").lower()).strip("_")
    return (normalized or fallback)[:64]


class JimengArkProvider:
    """Persist first, submit remotely later, and publish only local immutable files."""

    name = "jimeng-ark"

    def __init__(
        self,
        catalog: media.MediaCatalog,
        *,
        client: ArkClient | None = None,
        now_fn: Callable[[], datetime] | None = None,
        storage_root: str | Path | None = None,
        model: str | None = None,
        reference_image_url: str | None = None,
        poll_seconds: int | None = None,
        task_timeout_seconds: int | None = None,
        max_provider_failures: int | None = None,
        max_download_bytes: int | None = None,
    ):
        self.catalog = catalog
        self.now_fn = now_fn or (lambda: datetime.now(dt_timezone.utc))
        self.model = model or os.environ.get("LING_ARK_VIDEO_MODEL", DEFAULT_MODEL)
        self.reference_image_url = (
            reference_image_url
            if reference_image_url is not None
            else os.environ.get("LING_ARK_VIDEO_REFERENCE_IMAGE_URL", "").strip()
        )
        self.poll_seconds = poll_seconds or _env_int(
            "LING_ARK_VIDEO_POLL_SECONDS", 10, 2, 300
        )
        self.task_timeout_seconds = task_timeout_seconds or _env_int(
            "LING_ARK_VIDEO_TIMEOUT_SECONDS", 1800, 60, 259200
        )
        self.max_provider_failures = max_provider_failures or _env_int(
            "LING_ARK_VIDEO_MAX_FAILURES", 5, 1, 20
        )
        self.max_download_bytes = max_download_bytes or _env_int(
            "LING_MEDIA_MAX_DOWNLOAD_BYTES", 100 * 1024 * 1024, 1024, 1024 * 1024 * 1024
        )
        self.duration_seconds = _env_int("LING_ARK_VIDEO_DURATION_SECONDS", 6, 2, 12)
        self.resolution = os.environ.get("LING_ARK_VIDEO_RESOLUTION", "720p").strip()
        if self.resolution not in {"480p", "720p", "1080p"}:
            raise RuntimeError("LING_ARK_VIDEO_RESOLUTION must be 480p, 720p, or 1080p")
        self.storage_root = Path(storage_root) if storage_root else generated_media_root()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        if client is None:
            client = ArkHttpClient(
                _configured_api_key(),
                base_url=os.environ.get("LING_ARK_VIDEO_BASE_URL", DEFAULT_BASE_URL),
                timeout_seconds=_env_int("LING_ARK_VIDEO_HTTP_TIMEOUT_SECONDS", 30, 5, 300),
                download_timeout_seconds=_env_int(
                    "LING_ARK_VIDEO_DOWNLOAD_TIMEOUT_SECONDS", 180, 10, 1800
                ),
            )
        self.client = client

    def _now(self) -> datetime:
        return _aware(self.now_fn())

    @staticmethod
    def _query_one(conn, sql: str, params: tuple) -> dict | None:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _request_for_retry(self, request: dict, conn) -> dict:
        if request.get("prompt"):
            return dict(request)
        previous = self._query_one(
            conn,
            "SELECT request_json FROM generation_jobs WHERE moment_id=? "
            "AND attempt<? ORDER BY attempt DESC LIMIT 1",
            (request["moment_id"], request.get("attempt", 1)),
        )
        if not previous:
            return dict(request)
        try:
            restored = json.loads(previous["request_json"])
        except (TypeError, json.JSONDecodeError):
            return dict(request)
        restored.update(
            {
                "moment_id": request["moment_id"],
                "attempt": request.get("attempt", 1),
                "idempotency_key": request["idempotency_key"],
            }
        )
        return restored

    def submit(self, request: dict, *, conn=None) -> int:
        connection = conn or db.get_conn()
        existing = self._query_one(
            connection,
            "SELECT id FROM generation_jobs WHERE idempotency_key=?",
            (request["idempotency_key"],),
        )
        if existing:
            return existing["id"]
        request = self._request_for_retry(request, connection)
        if request.get("template_asset_id"):
            asset = self.catalog.asset(request["template_asset_id"])
        else:
            asset = self.catalog.select_asset(
                request["event_key"],
                request["event_value"],
                request["semantic_version"],
                request["idempotency_key"],
                request.get("allowed_asset_groups"),
            )
        request.setdefault("template_asset_id", asset["asset_id"])
        request.setdefault("asset_group", asset["asset_group"])
        request.setdefault("alt", asset["alt"])
        request.setdefault("moment", asset.get("moment"))
        request.setdefault(
            "prompt",
            _video_prompt(asset, has_reference=bool(self.reference_image_url)),
        )
        request.setdefault(
            "generation_config",
            {
                "model": self.model,
                "reference_image_url": self.reference_image_url,
                "generate_audio": False,
                "return_last_frame": True,
                "resolution": self.resolution,
                "ratio": "9:16",
                "duration": self.duration_seconds,
                "watermark": False,
            },
        )
        now = self._now()
        cursor = connection.execute(
            "INSERT INTO generation_jobs("
            "moment_id,attempt,media_kind,provider,asset_group,status,idempotency_key,"
            "created_at,ready_at,updated_at,request_json,next_poll_at) "
            "VALUES(?,?,?,?,?,'queued',?,?,?,?,?,?)",
            (
                request["moment_id"],
                request.get("attempt", 1),
                request["media_kind"],
                self.name,
                request["asset_group"],
                request["idempotency_key"],
                _iso(now),
                _iso(now),
                _iso(now),
                json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                _iso(now),
            ),
        )
        if conn is None:
            connection.commit()
        return cursor.lastrowid

    def _claim(self, job_id: int) -> tuple[dict, bool]:
        now = self._now()
        with db.transaction(immediate=True) as conn:
            row = self._query_one(
                conn, "SELECT * FROM generation_jobs WHERE id=?", (job_id,)
            )
            if not row:
                raise media.MediaNotFound(f"job not found: {job_id}")
            if row["status"] in TERMINAL_STATUSES:
                return row, False
            due_at = _from_iso(row.get("next_poll_at"))
            if due_at and due_at > now:
                return row, False
            lease_until = now + timedelta(seconds=max(30, self.poll_seconds * 3))
            conn.execute(
                "UPDATE generation_jobs SET next_poll_at=?,updated_at=? "
                "WHERE id=? AND status IN ('queued','running')",
                (_iso(lease_until), _iso(now), job_id),
            )
            row["next_poll_at"] = _iso(lease_until)
            return row, True

    def _create_payload(self, request: dict) -> dict:
        config = request.get("generation_config")
        if not isinstance(config, dict):
            config = {}
        content = [{"type": "text", "text": request["prompt"]}]
        reference_image_url = config.get(
            "reference_image_url", self.reference_image_url
        )
        if reference_image_url:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": reference_image_url},
                    "role": "reference_image",
                }
            )
        return {
            "model": config.get("model", self.model),
            "content": content,
            "generate_audio": config.get("generate_audio", False),
            "return_last_frame": config.get("return_last_frame", True),
            "resolution": config.get("resolution", self.resolution),
            "ratio": config.get("ratio", "9:16"),
            "duration": config.get("duration", self.duration_seconds),
            "watermark": config.get("watermark", False),
        }

    def _retry_or_fail(
        self, row: dict, error: ArkRequestError, *, fallback_code: str
    ) -> str:
        failures = int(row.get("provider_failures") or 0) + 1
        now = self._now()
        hard_failure = not error.retryable or failures >= self.max_provider_failures
        if hard_failure:
            status = "failed"
            next_poll_at = None
        else:
            status = row["status"]
            delay = min(300, self.poll_seconds * (2 ** min(failures, 5)))
            next_poll_at = _iso(now + timedelta(seconds=delay))
        db.execute(
            "UPDATE generation_jobs SET status=?,provider_failures=?,error_code=?,"
            "next_poll_at=?,updated_at=? WHERE id=? AND status IN ('queued','running')",
            (
                status,
                failures,
                _safe_error_code(error.status, fallback_code),
                next_poll_at,
                _iso(now),
                row["id"],
            ),
        )
        return status

    def _remote_failed(self, row: dict, response: dict) -> str:
        error = response.get("error") if isinstance(response.get("error"), dict) else {}
        code = _safe_error_code(error.get("code") or response.get("status"), "remote_failed")
        db.execute(
            "UPDATE generation_jobs SET status='failed',error_code=?,"
            "provider_response_json=?,next_poll_at=NULL,updated_at=? "
            "WHERE id=? AND status IN ('queued','running')",
            (
                code,
                json.dumps(response, ensure_ascii=False, separators=(",", ":")),
                _iso(self._now()),
                row["id"],
            ),
        )
        return "failed"

    @staticmethod
    def _dimensions(request: dict, content: dict) -> tuple[int, int]:
        if isinstance(content.get("width"), int) and isinstance(content.get("height"), int):
            return content["width"], content["height"]
        resolution = str(content.get("resolution") or request.get("resolution") or "720p")
        short_edge = {"480p": 480, "720p": 720, "1080p": 1080}.get(resolution, 720)
        return short_edge, round(short_edge * 16 / 9)

    def _finalize_success(self, row: dict, response: dict) -> str:
        content = response.get("content")
        if not isinstance(content, dict) or not isinstance(content.get("video_url"), str):
            return self._remote_failed(
                row,
                {**response, "error": {"code": "missing_video_url"}},
            )
        request = json.loads(row["request_json"])
        generation_config = request.get("generation_config")
        if not isinstance(generation_config, dict):
            generation_config = {}
        external_id = row["external_task_id"]
        stable = hashlib.sha256(external_id.encode("utf-8")).hexdigest()[:16]
        basename = f"job-{row['id']}-{stable}"
        video_path = self.storage_root / f"{basename}.mp4"
        video_temp = self.storage_root / f".{basename}.mp4.part"
        poster_path: Path | None = None
        poster_sha256: str | None = None
        try:
            self.client.download(content["video_url"], video_temp, self.max_download_bytes)
            _validate_mp4(video_temp)
            video_temp.replace(video_path)
            last_frame_url = content.get("last_frame_url")
            if isinstance(last_frame_url, str) and last_frame_url:
                poster_temp = self.storage_root / f".{basename}.poster.part"
                try:
                    self.client.download(
                        last_frame_url, poster_temp, min(self.max_download_bytes, 20 * 1024 * 1024)
                    )
                    extension = _image_extension(poster_temp)
                    if extension:
                        poster_path = self.storage_root / f"{basename}{extension}"
                        poster_temp.replace(poster_path)
                        poster_sha256 = _sha256(poster_path)
                    else:
                        poster_temp.unlink(missing_ok=True)
                except ArkRequestError:
                    poster_temp.unlink(missing_ok=True)
        except ArkRequestError as exc:
            video_temp.unlink(missing_ok=True)
            return self._retry_or_fail(row, exc, fallback_code="download_failed")
        except media.MediaGenerationFailed:
            video_temp.unlink(missing_ok=True)
            video_path.unlink(missing_ok=True)
            return self._remote_failed(
                row,
                {**response, "error": {"code": "invalid_generated_media"}},
            )

        width, height = self._dimensions(
            {"resolution": generation_config.get("resolution", self.resolution)},
            content,
        )
        duration = content.get("duration")
        duration_ms = (
            round(float(duration) * 1000)
            if isinstance(duration, (int, float))
            else int(generation_config.get("duration", self.duration_seconds)) * 1000
        )
        asset_id = f"jimeng-{_safe_error_code(external_id, stable)}"
        now = self._now()
        db.execute(
            "UPDATE generation_jobs SET status='succeeded',asset_id=?,"
            "provider_response_json=?,provider_failures=0,error_code='',next_poll_at=NULL,"
            "media_path=?,poster_path=?,media_sha256=?,poster_sha256=?,"
            "width=?,height=?,duration_ms=?,completed_at=?,updated_at=? "
            "WHERE id=? AND status IN ('queued','running')",
            (
                asset_id,
                json.dumps(response, ensure_ascii=False, separators=(",", ":")),
                video_path.name,
                poster_path.name if poster_path else None,
                _sha256(video_path),
                poster_sha256,
                width,
                height,
                duration_ms,
                _iso(now),
                _iso(now),
                row["id"],
            ),
        )
        return "succeeded"

    def poll(self, job_id: int) -> str:
        row, claimed = self._claim(job_id)
        if not claimed:
            return row["status"]
        now = self._now()
        created_at = _from_iso(row["created_at"])
        if created_at and (now - created_at).total_seconds() > self.task_timeout_seconds:
            db.execute(
                "UPDATE generation_jobs SET status='failed',error_code='provider_timeout',"
                "next_poll_at=NULL,updated_at=? WHERE id=? AND status IN ('queued','running')",
                (_iso(now), job_id),
            )
            return "failed"
        try:
            if not row.get("external_task_id"):
                request = json.loads(row["request_json"])
                response = self.client.create_task(self._create_payload(request))
                task_id = response.get("id")
                if not isinstance(task_id, str) or not task_id:
                    return self._remote_failed(
                        row, {**response, "error": {"code": "missing_task_id"}}
                    )
                next_poll = now + timedelta(seconds=self.poll_seconds)
                db.execute(
                    "UPDATE generation_jobs SET status='running',external_task_id=?,"
                    "provider_response_json=?,provider_failures=0,error_code='',"
                    "next_poll_at=?,updated_at=? WHERE id=? AND status='queued'",
                    (
                        task_id,
                        json.dumps(response, ensure_ascii=False, separators=(",", ":")),
                        _iso(next_poll),
                        _iso(now),
                        job_id,
                    ),
                )
                return "running"

            response = self.client.get_task(row["external_task_id"])
        except (json.JSONDecodeError, TypeError) as exc:
            return self._remote_failed(
                row, {"error": {"code": "invalid_request_snapshot", "message": str(exc)}}
            )
        except ArkRequestError as exc:
            return self._retry_or_fail(row, exc, fallback_code="provider_unavailable")

        remote_status = str(response.get("status") or "").lower()
        if remote_status in REMOTE_FAILED_STATUSES:
            return self._remote_failed(row, response)
        if remote_status == "succeeded":
            return self._finalize_success(row, response)
        if remote_status not in {"queued", "running"}:
            return self._retry_or_fail(
                row,
                ArkRequestError(
                    f"unknown Ark task status: {remote_status or 'missing'}"
                ),
                fallback_code="unknown_provider_status",
            )
        next_poll = now + timedelta(seconds=self.poll_seconds)
        db.execute(
            "UPDATE generation_jobs SET status='running',provider_response_json=?,"
            "provider_failures=0,error_code='',next_poll_at=?,updated_at=? "
            "WHERE id=? AND status IN ('queued','running')",
            (
                json.dumps(response, ensure_ascii=False, separators=(",", ":")),
                _iso(next_poll),
                _iso(now),
                job_id,
            ),
        )
        return "running"

    def result(self, job_id: int) -> dict:
        row = db.q1("SELECT * FROM generation_jobs WHERE id=?", (job_id,))
        if not row:
            raise media.MediaNotFound(f"job not found: {job_id}")
        if row["status"] == "failed":
            raise media.MediaGenerationFailed(row.get("error_code") or "generation_failed")
        if row["status"] != "succeeded":
            raise media.MediaNotReady(f"job {job_id} is {row['status']}")
        request = json.loads(row["request_json"])
        generation_config = request.get("generation_config")
        if not isinstance(generation_config, dict):
            generation_config = {}
        template = self.catalog.asset(request["template_asset_id"])
        if row.get("poster_path"):
            poster = f"/generated-media/{row['poster_path']}"
            poster_sha = row.get("poster_sha256") or ""
        else:
            poster = media.MediaCatalog.public_asset(template)["poster"]
            poster_sha = (template.get("sha256") or {}).get("poster", "")
        return {
            "asset_id": row["asset_id"],
            "media_kind": "video",
            "event_key": request["event_key"],
            "event_value": request["event_value"],
            "asset_group": row["asset_group"],
            "semantic_version": request["semantic_version"],
            "src": f"/generated-media/{row['media_path']}",
            "poster": poster,
            "mime_type": "video/mp4",
            "width": row.get("width") or 720,
            "height": row.get("height") or 1280,
            "duration_ms": row.get("duration_ms")
            or int(generation_config.get("duration", self.duration_seconds)) * 1000,
            "alt": request.get("alt") or template["alt"],
            "sha256": {
                "media": row.get("media_sha256") or "",
                "poster": poster_sha,
            },
            "moment": request.get("moment"),
            "provenance": {
                "provider": self.name,
                "model": generation_config.get("model", self.model),
                "external_task_id": row["external_task_id"],
                "prompt_sha256": hashlib.sha256(
                    request["prompt"].encode("utf-8")
                ).hexdigest(),
                "generated_at": row.get("completed_at"),
            },
        }


def configured_provider(
    catalog: media.MediaCatalog,
    *,
    now_fn: Callable[[], datetime] | None = None,
    generation_delay_seconds: int = 3,
) -> media.GenerationProvider:
    mode = provider_mode_info()
    provider = mode["requested_provider"]
    if mode["active_provider"] == "mock":
        return media.MockMediaProvider(
            catalog, now_fn=now_fn, delay_seconds=generation_delay_seconds
        )
    if provider in JIMENG_PROVIDER_ALIASES:
        return JimengArkProvider(catalog, now_fn=now_fn)
    raise RuntimeError(
        "LING_MEDIA_PROVIDER must be mock or jimeng (aliases: ark, seedance)"
    )
