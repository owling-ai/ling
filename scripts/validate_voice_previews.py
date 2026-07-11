#!/usr/bin/env python3
"""Validate bundled RTC child-voice previews and their provenance manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import wave
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import voice_profiles  # noqa: E402


SAMPLE_RATE = 24000
PRIVATE_MANIFEST_FIELDS = {
    "api_key",
    "access_key",
    "model",
    "provider_params",
    "resource_id",
    "secret_key",
    "style_instruction",
    "tts_model",
    "voice",
}


def _reject_private_fields(value, path: str = "manifest") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in PRIVATE_MANIFEST_FIELDS:
                raise RuntimeError(f"private upstream field in public {path}: {key}")
            _reject_private_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_private_fields(child, f"{path}[{index}]")


def validate(root: Path) -> list[dict]:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _reject_private_fields(manifest)
    expected_ids = [profile["id"] for profile in voice_profiles.VOICE_PROFILES]
    items = manifest.get("profiles") or []
    if [item.get("id") for item in items] != expected_ids:
        raise RuntimeError("manifest profiles do not match the server allowlist")
    if manifest.get("pipeline") != "production-rtc-recording":
        raise RuntimeError("previews must come from the production RTC transport")

    results = []
    for item in items:
        path = root / item["file"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != item["sha256"]:
            raise RuntimeError(f"SHA-256 mismatch: {path}")
        with wave.open(str(path), "rb") as audio:
            if (
                audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or audio.getframerate() != SAMPLE_RATE
            ):
                raise RuntimeError(f"invalid WAV format: {path}")
            frames = audio.readframes(audio.getnframes())
            duration = audio.getnframes() / audio.getframerate()
        if abs(duration - float(item["duration_seconds"])) > 0.001:
            raise RuntimeError(f"duration mismatch: {path}")
        samples = array("h")
        samples.frombytes(frames)
        peak = max((abs(sample) for sample in samples), default=0)
        if peak >= 32767:
            raise RuntimeError(f"clipped preview: {path}")
        review = item.get("review") or {}
        if (
            review.get("verdict") != "pass"
            or int(review.get("child_likeness", 0)) < 7
            or int(review.get("adult_imitation_risk", 10)) > 3
            or int(review.get("cartoon_risk", 10)) > 4
            or int(review.get("long_chat_comfort", 0)) < 7
        ):
            raise RuntimeError(f"review gate failed: {path}")
        results.append(
            {
                "id": item["id"],
                "duration_seconds": duration,
                "peak": peak,
                "sha256": digest,
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--voice-dir",
        type=Path,
        default=ROOT / "frontend" / "assets" / "voices",
    )
    args = parser.parse_args()
    for result in validate(args.voice_dir):
        print(
            f"{result['id']}: {result['duration_seconds']:.3f}s, "
            f"peak={result['peak']}, sha256={result['sha256']}"
        )


if __name__ == "__main__":
    main()
