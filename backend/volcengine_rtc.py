"""Volcengine AI audio/video control plane and RTC token service.

The browser carries media through the ByteRTC Web SDK. This module only issues
short-lived room tokens, signs Volcengine OpenAPI requests, controls the AI bot,
and commits final subtitle messages to Ling's conversation engine.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import OrderedDict
from datetime import datetime, timezone

from . import engine, prompts, realtime


APP_ID = os.environ.get("VOLCENGINE_RTC_APP_ID", "")
APP_KEY = os.environ.get("VOLCENGINE_RTC_APP_KEY", "")
ACCESS_KEY = os.environ.get("VOLCENGINE_ACCESS_KEY", "")
SECRET_KEY = os.environ.get("VOLCENGINE_SECRET_KEY", "")
BUSINESS_ID = os.environ.get("LING_VOLC_BUSINESS_ID", "")

ARK_MODEL = os.environ.get(
    "LING_VOLC_ARK_MODEL", "doubao-seed-2-1-turbo-260628"
)
ASR_RESOURCE_ID = os.environ.get(
    "LING_VOLC_ASR_RESOURCE_ID", "volc.bigasr.sauc.duration"
)
TTS_RESOURCE_ID = os.environ.get(
    "LING_VOLC_TTS_RESOURCE_ID", "volc.service_type.10029"
)
TTS_VOICE = os.environ.get(
    "LING_VOLC_TTS_VOICE", "zh_female_linjianvhai_moon_bigtts"
)
TOKEN_TTL_SECONDS = int(os.environ.get("LING_VOLC_TOKEN_TTL_SECONDS", "3600"))
IDLE_TIMEOUT_SECONDS = int(os.environ.get("LING_VOLC_IDLE_TIMEOUT_SECONDS", "30"))
VISION_INTERVAL_MS = int(os.environ.get("LING_VOLC_VISION_INTERVAL_MS", "1000"))

OPENAPI_HOST = "rtc.volcengineapi.com"
OPENAPI_VERSION = "2025-06-01"
OPENAPI_REGION = "cn-north-1"
OPENAPI_SERVICE = "rtc"

PRIV_PUBLISH_STREAM = 0
PRIV_SUBSCRIBE_STREAM = 4

# session_id -> identifiers issued for one ByteRTC room and AI task.
TASKS: dict[str, dict] = {}


def available() -> bool:
    return all((APP_ID, APP_KEY, ACCESS_KEY, SECRET_KEY))


def missing_env() -> list[str]:
    values = {
        "VOLCENGINE_RTC_APP_ID": APP_ID,
        "VOLCENGINE_RTC_APP_KEY": APP_KEY,
        "VOLCENGINE_ACCESS_KEY": ACCESS_KEY,
        "VOLCENGINE_SECRET_KEY": SECRET_KEY,
    }
    return [name for name, value in values.items() if not value]


def _pack_uint16(value: int) -> bytes:
    return struct.pack("<H", int(value))


def _pack_uint32(value: int) -> bytes:
    return struct.pack("<I", int(value))


def _pack_bytes(value: bytes) -> bytes:
    return _pack_uint16(len(value)) + value


def _pack_string(value: str) -> bytes:
    return _pack_bytes(value.encode("utf-8"))


def _pack_privileges(privileges: dict[int, int]) -> bytes:
    ordered = OrderedDict(sorted(privileges.items(), key=lambda item: item[0]))
    result = _pack_uint16(len(ordered))
    for key, value in ordered.items():
        result += _pack_uint16(key) + _pack_uint32(value)
    return result


def create_rtc_token(room_id: str, user_id: str, ttl_seconds: int | None = None) -> str:
    """Generate the official ByteRTC 001 access-token format."""
    now = int(time.time())
    expires_at = now + (ttl_seconds or TOKEN_TTL_SECONDS)
    privileges = {
        PRIV_PUBLISH_STREAM: expires_at,
        1: expires_at,  # audio, video and data privileges from the official sample
        2: expires_at,
        3: expires_at,
        PRIV_SUBSCRIBE_STREAM: expires_at,
    }
    message = b"".join(
        (
            _pack_uint32(secrets.randbelow(99_999_999) + 1),
            _pack_uint32(now),
            _pack_uint32(expires_at),
            _pack_string(room_id),
            _pack_string(user_id),
            _pack_privileges(privileges),
        )
    )
    signature = hmac.new(APP_KEY.encode("utf-8"), message, hashlib.sha256).digest()
    content = _pack_bytes(message) + _pack_bytes(signature)
    return "001" + APP_ID + base64.b64encode(content).decode("ascii")


def _normalized_query(parameters: dict[str, str]) -> str:
    return urllib.parse.urlencode(
        sorted(parameters.items()), quote_via=urllib.parse.quote, safe="-_.~"
    )


def _hmac_sha256(key: bytes, content: str) -> bytes:
    return hmac.new(key, content.encode("utf-8"), hashlib.sha256).digest()


def _openapi_headers(action: str, body: str) -> tuple[dict[str, str], str]:
    x_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_date = x_date[:8]
    body_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    query = _normalized_query({"Action": action, "Version": OPENAPI_VERSION})
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical_headers = "\n".join(
        (
            "content-type:application/json",
            f"host:{OPENAPI_HOST}",
            f"x-content-sha256:{body_hash}",
            f"x-date:{x_date}",
        )
    )
    canonical_request = "\n".join(
        ("POST", "/", query, canonical_headers, "", signed_headers, body_hash)
    )
    scope = f"{short_date}/{OPENAPI_REGION}/{OPENAPI_SERVICE}/request"
    string_to_sign = "\n".join(
        (
            "HMAC-SHA256",
            x_date,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        )
    )
    date_key = _hmac_sha256(SECRET_KEY.encode("utf-8"), short_date)
    region_key = _hmac_sha256(date_key, OPENAPI_REGION)
    service_key = _hmac_sha256(region_key, OPENAPI_SERVICE)
    signing_key = _hmac_sha256(service_key, "request")
    signature = _hmac_sha256(signing_key, string_to_sign).hex()
    authorization = (
        f"HMAC-SHA256 Credential={ACCESS_KEY}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Host": OPENAPI_HOST,
        "Content-Type": "application/json",
        "X-Date": x_date,
        "X-Content-Sha256": body_hash,
        "Authorization": authorization,
    }, query


def _openapi(action: str, payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    headers, query = _openapi_headers(action, body)
    request = urllib.request.Request(
        f"https://{OPENAPI_HOST}/?{query}",
        data=body.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Volcengine {action} HTTP {exc.code}: {detail[:500]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Volcengine {action} network error: {exc.reason}") from exc
    if result.get("ResponseMetadata", {}).get("Error"):
        error = result["ResponseMetadata"]["Error"]
        raise RuntimeError(
            f"Volcengine {action}: {error.get('Code', 'error')} "
            f"{error.get('Message', '')}"
        )
    return result


def prepare(session_id: str) -> dict:
    if not available():
        raise RuntimeError("missing " + ", ".join(missing_env()))
    if not engine.get_session(session_id):
        raise KeyError("session not found")
    task = TASKS.get(session_id)
    if not task:
        suffix = uuid.uuid4().hex[:16]
        room_id = f"ling-{session_id}-{suffix}"
        user_id = f"ling-user-{suffix}"
        task = {
            "session_id": session_id,
            "room_id": room_id,
            "user_id": user_id,
            "task_id": f"ling-task-{suffix}",
            "bot_id": f"ling-bot-{suffix}",
            "status": "prepared",
            "recorded_subtitles": set(),
            "last_user_final_at": None,
        }
        TASKS[session_id] = task
    return {
        "app_id": APP_ID,
        "room_id": task["room_id"],
        "user_id": task["user_id"],
        "task_id": task["task_id"],
        "bot_id": task["bot_id"],
        "token": create_rtc_token(task["room_id"], task["user_id"]),
        "expires_in": TOKEN_TTL_SECONDS,
    }


def _start_payload(task: dict, pack: dict) -> dict:
    child_name = (pack.get("child_card") or {}).get("name", "小朋友")
    doll_name = (pack.get("doll_card") or {}).get("name", "灵灵")
    system_message = prompts.build_doll_system(pack) + realtime.VOICE_NOTE
    payload = {
        "AppId": APP_ID,
        "RoomId": task["room_id"],
        "TaskId": task["task_id"],
        "Config": {
            "ASRConfig": {
                "Provider": "volcano",
                "ProviderParams": {
                    "Mode": "bigmodel",
                    "VolcanoASRParameters": json.dumps(
                        {"request": {"enable_nonstream": True}}, separators=(",", ":")
                    ),
                    "Credential": {"ApiResourceId": ASR_RESOURCE_ID},
                    "StreamMode": 2,
                    "ContextHistoryLength": 3,
                },
            },
            "VADConfig": {"SilenceTime": 600},
            "LLMConfig": {
                "Mode": "ArkV3",
                "ModelName": ARK_MODEL,
                "SystemMessages": [system_message],
                "HistoryLength": 10,
                "Temperature": 0.7,
                "MaxTokens": 180,
                "ThinkingType": "disabled",
                "Prefill": True,
                "VisionConfig": {
                    "Enable": True,
                    "SnapshotConfig": {
                        "StreamType": 0,
                        "ImageDetail": "low",
                        "Height": 360,
                        "Interval": VISION_INTERVAL_MS,
                        "ImagesLimit": 1,
                    },
                },
            },
            "TTSConfig": {
                "Provider": "volcano_bidirection",
                "ProviderParams": {
                    "ResourceId": TTS_RESOURCE_ID,
                    "audio": {"voice_type": TTS_VOICE, "speech_rate": 0},
                },
            },
            "InterruptMode": 0,
            "SubtitleConfig": {"DisableRTSSubtitle": False, "SubtitleMode": 1},
        },
        "AgentConfig": {
            "TargetUserId": [task["user_id"]],
            "UserId": task["bot_id"],
            "WelcomeMessage": f"嗨，{child_name}，{doll_name}在呢！",
            "IdleTimeout": IDLE_TIMEOUT_SECONDS,
            "VoicePrint": {
                "Mode": 1,
                "VoiceDuration": 4,
                "EnableSV": True,
            },
        },
    }
    if BUSINESS_ID:
        payload["BusinessId"] = BUSINESS_ID
    return payload


def start(session_id: str) -> dict:
    task = TASKS.get(session_id)
    session = engine.get_session(session_id)
    if not task or not session:
        raise KeyError("session is not prepared")
    if task["status"] == "active":
        return {"ok": True, "task_id": task["task_id"], "bot_id": task["bot_id"]}
    _openapi("StartVoiceChat", _start_payload(task, session["pack"]))
    task["status"] = "active"
    return {"ok": True, "task_id": task["task_id"], "bot_id": task["bot_id"]}


def observe(session_id: str) -> dict:
    task = TASKS.get(session_id)
    session = engine.get_session(session_id)
    if not task or task["status"] != "active" or not session:
        raise KeyError("active Volcengine task not found")
    nudge_number = engine.claim_idle_nudge(session_id)
    if not nudge_number:
        return {"ok": False, "reason": "budget_exhausted"}
    message = realtime._idle_instruction(session["pack"], nudge_number)
    try:
        _openapi(
            "UpdateVoiceChat",
            {
                "AppId": APP_ID,
                "RoomId": task["room_id"],
                "TaskId": task["task_id"],
                "Command": "ExternalTextToLLM",
                "Message": message,
                "InterruptMode": 2,
            },
        )
    except Exception:
        session["idle_nudges"] = max(0, session.get("idle_nudges", 1) - 1)
        raise
    return {"ok": True, "nudge_number": nudge_number}


def stop(session_id: str) -> dict:
    task = TASKS.get(session_id)
    if not task:
        return {"ok": True}
    if task["status"] == "active":
        _openapi(
            "StopVoiceChat",
            {
                "AppId": APP_ID,
                "RoomId": task["room_id"],
                "TaskId": task["task_id"],
            },
        )
    TASKS.pop(session_id, None)
    return {"ok": True}


def record_subtitle(
    session_id: str,
    speaker_id: str,
    text: str,
    sequence: int,
    round_id: int,
    definite: bool,
) -> dict:
    task = TASKS.get(session_id)
    if not task or speaker_id not in (task["user_id"], task["bot_id"]):
        raise KeyError("subtitle task or speaker not found")
    role = "user" if speaker_id == task["user_id"] else "assistant"
    text = (text or "").strip()
    result = {"ok": True, "role": role}
    if not definite or not text:
        return result
    key = (speaker_id, round_id, sequence, text)
    if key in task["recorded_subtitles"]:
        return result
    task["recorded_subtitles"].add(key)
    if role == "user":
        task["last_user_final_at"] = time.monotonic()
        engine.record_voice_user(session_id, text)
    else:
        if task.get("last_user_final_at") is not None:
            latency = time.monotonic() - task["last_user_final_at"]
            print(f"[volcengine] response subtitle latency={latency:.2f}s", flush=True)
            task["last_user_final_at"] = None
        state = engine.record_voice_doll(session_id, text)
        if state:
            result["state"] = state
    return result
