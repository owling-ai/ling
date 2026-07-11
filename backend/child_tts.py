"""Server-only child-voice TTS for legacy PCM hardware transports."""

from __future__ import annotations

import base64
import binascii
import json
import os
import urllib.error
import urllib.request
import uuid

from . import voice_profiles


TTS_URL = os.environ.get(
    "LING_VOLC_SPEECH_TTS_URL",
    "https://openspeech.bytedance.com/api/v3/tts/unidirectional",
).strip()
TTS_RESOURCE_ID = "seed-tts-2.0"
TTS_SAMPLE_RATE = 24000
TTS_TIMEOUT_SECONDS = max(
    5, int(os.environ.get("LING_VOLC_SPEECH_TTS_TIMEOUT_SECONDS", "30"))
)
TTS_MAX_TEXT_CHARS = max(
    100, int(os.environ.get("LING_VOLC_SPEECH_TTS_MAX_TEXT_CHARS", "1000"))
)
TTS_MAX_AUDIO_BYTES = max(
    1_000_000,
    int(os.environ.get("LING_VOLC_SPEECH_TTS_MAX_AUDIO_BYTES", "5000000")),
)


def available() -> bool:
    return bool(os.environ.get("VOLCENGINE_SPEECH_API_KEY", "").strip())


def synthesize_pcm(text: str, profile_id: str | None = None) -> bytes:
    api_key = os.environ.get("VOLCENGINE_SPEECH_API_KEY", "").strip()
    normalized = " ".join(str(text or "").split()).strip()
    if not api_key:
        raise RuntimeError("Volcengine Speech API key is not configured")
    if not normalized:
        return b""
    if len(normalized) > TTS_MAX_TEXT_CHARS:
        raise RuntimeError("TTS text is too long")

    profile = voice_profiles.resolve_voice_profile(profile_id)
    body = json.dumps(
        {
            "req_params": {
                "text": normalized,
                "speaker": profile["voice"],
                "audio_params": {
                    "format": "pcm",
                    "sample_rate": TTS_SAMPLE_RATE,
                    "speech_rate": 0,
                },
                "context_texts": [profile["style_instruction"]],
            }
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        TTS_URL,
        data=body,
        method="POST",
        headers={
            "X-Api-Key": api_key,
            "X-Api-Resource-Id": TTS_RESOURCE_ID,
            "X-Api-Request-Id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        },
    )

    audio = bytearray()
    try:
        with urllib.request.urlopen(request, timeout=TTS_TIMEOUT_SECONDS) as response:
            for raw_line in response:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError("Volcengine TTS returned invalid JSON") from exc
                code = int(event.get("code") or 0)
                if code not in {0, 20_000_000}:
                    raise RuntimeError(
                        f"Volcengine TTS error {code}: {event.get('message', '')}"
                    )
                encoded = event.get("data")
                if not encoded:
                    continue
                try:
                    chunk = base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise RuntimeError("Volcengine TTS returned invalid audio") from exc
                if len(audio) + len(chunk) > TTS_MAX_AUDIO_BYTES:
                    raise RuntimeError("Volcengine TTS audio exceeded the size limit")
                audio.extend(chunk)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Volcengine TTS HTTP {exc.code}: {detail[:300]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Volcengine TTS network error: {exc.reason}") from exc

    if not audio:
        raise RuntimeError("Volcengine TTS returned no audio")
    return bytes(audio)
