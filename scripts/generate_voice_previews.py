#!/usr/bin/env python3
"""Generate the bundled Gemini Live voice-profile previews."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import sys
import wave
from datetime import datetime, timezone
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import realtime  # noqa: E402

PREVIEW_TEXT = (
    "嗨，我是灵灵。今天见到你真开心！"
    "你想先聊小风筝，还是一起说 butterfly？"
)
REQUIRED_TRANSCRIPT_TERMS = ("灵灵", "开心", "butterfly")
SAMPLE_RATE = 24000


def _setup(profile: dict) -> dict:
    model = realtime.GEMINI_MODEL
    if not model.startswith("models/"):
        model = f"models/{model}"
    return {
        "setup": {
            "model": model,
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": profile["voice"]}
                    }
                },
            },
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "你正在为儿童陪伴玩偶灵灵录制一段声音试听。"
                            f"整段使用以下听感：{profile['style_instruction']}"
                            "必须逐字朗读用户给出的台词，不添加前后缀，不解释要求，"
                            "不念标点名称。"
                        )
                    }
                ]
            },
            "outputAudioTranscription": {},
        }
    }


async def _generate_once(profile: dict) -> tuple[bytes, str]:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is required")

    async with websockets.connect(
        realtime.GEMINI_URL,
        additional_headers={"x-goog-api-key": api_key},
        open_timeout=20,
        close_timeout=5,
        max_size=8 * 1024 * 1024,
    ) as upstream:
        await upstream.send(json.dumps(_setup(profile), ensure_ascii=False))
        first = json.loads(await asyncio.wait_for(upstream.recv(), timeout=20))
        if "setupComplete" not in first:
            error = first.get("error") or {}
            raise RuntimeError(error.get("message") or "Gemini setup failed")

        await upstream.send(
            json.dumps(
                {
                    "clientContent": {
                        "turns": [
                            {
                                "role": "user",
                                "parts": [{"text": PREVIEW_TEXT}],
                            }
                        ],
                        "turnComplete": True,
                    }
                },
                ensure_ascii=False,
            )
        )

        audio = bytearray()
        transcript: list[str] = []

        async def collect_response() -> None:
            async for raw in upstream:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                event = json.loads(raw)
                if event.get("error"):
                    error = event["error"]
                    raise RuntimeError(error.get("message") or "Gemini generation failed")
                content = event.get("serverContent") or {}
                for part in (content.get("modelTurn") or {}).get("parts") or []:
                    inline = part.get("inlineData") or {}
                    encoded = inline.get("data")
                    if encoded:
                        audio.extend(base64.b64decode(encoded, validate=True))
                text = (content.get("outputTranscription") or {}).get("text")
                if text:
                    transcript.append(text)
                if content.get("turnComplete"):
                    return

        await asyncio.wait_for(collect_response(), timeout=45)

    return bytes(audio), "".join(transcript).strip()


def _validate(audio: bytes, transcript: str) -> float:
    if not audio or len(audio) % 2:
        raise RuntimeError("Gemini returned invalid PCM16 audio")
    duration = len(audio) / (SAMPLE_RATE * 2)
    if not 3.0 <= duration <= 20.0:
        raise RuntimeError(f"unexpected preview duration: {duration:.2f}s")
    normalized = transcript.casefold().replace(" ", "")
    missing = [term for term in REQUIRED_TRANSCRIPT_TERMS if term.casefold() not in normalized]
    if missing:
        raise RuntimeError(
            f"preview transcript is missing {missing}: {transcript!r}"
        )
    return duration


async def _generate(profile: dict, attempts: int = 3) -> tuple[bytes, str, float]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            audio, transcript = await _generate_once(profile)
            return audio, transcript, _validate(audio, transcript)
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                await asyncio.sleep(attempt)
    raise RuntimeError(
        f"failed to generate {profile['id']} after {attempts} attempts: {last_error}"
    ) from last_error


def _write_wav(path: Path, pcm: bytes) -> None:
    temporary = path.with_suffix(".tmp")
    with wave.open(str(temporary), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm)
    temporary.replace(path)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "frontend" / "assets" / "voices",
    )
    parser.add_argument("--profile", action="append", dest="profile_ids")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    profiles = [
        realtime.resolve_gemini_voice_profile(profile["id"])
        for profile in realtime.GEMINI_VOICE_PROFILES
        if not args.profile_ids or profile["id"] in args.profile_ids
    ]
    if args.profile_ids and len(profiles) != len(set(args.profile_ids)):
        known = ", ".join(profile["id"] for profile in realtime.GEMINI_VOICE_PROFILES)
        raise SystemExit(f"unknown profile; choose from: {known}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "manifest.json"
    previous_profiles: dict[str, dict] = {}
    if args.profile_ids and manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        previous_profiles = {
            item["id"]: item for item in previous.get("profiles", [])
        }
    manifest = {
        "model": realtime.GEMINI_MODEL,
        "sample_rate": SAMPLE_RATE,
        "preview_text": PREVIEW_TEXT,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "profiles": [],
    }

    for profile in profiles:
        output = args.output_dir / f"{profile['id']}.wav"
        if output.exists() and not args.force:
            raise SystemExit(f"{output} already exists; pass --force to regenerate")
        pcm, transcript, duration = await _generate(profile)
        _write_wav(output, pcm)
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        previous_profiles[profile["id"]] = {
            "id": profile["id"],
            "name": profile["name"],
            "voice": profile["voice"],
            "description": profile["description"],
            "file": output.name,
            "duration_seconds": round(duration, 3),
            "transcript": transcript,
            "sha256": digest,
        }
        print(
            f"generated {profile['id']}: {duration:.2f}s, "
            f"{len(pcm)} PCM bytes, transcript={transcript!r}"
        )

    manifest["profiles"] = [
        previous_profiles[profile["id"]]
        for profile in realtime.GEMINI_VOICE_PROFILES
        if profile["id"] in previous_profiles
    ]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    asyncio.run(main())
