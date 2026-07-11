"""Volcengine streaming ASR client for legacy 16 kHz PCM devices."""

from __future__ import annotations

import gzip
import inspect
import json
import os
import struct
import uuid
from collections.abc import AsyncIterator


ASR_URL = os.environ.get(
    "LING_VOLC_SPEECH_ASR_URL",
    "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async",
).strip()
ASR_RESOURCE_ID = os.environ.get(
    "LING_VOLC_SPEECH_ASR_RESOURCE_ID",
    "volc.bigasr.sauc.duration",
).strip()
ASR_SAMPLE_RATE = 16000


def available() -> bool:
    return bool(os.environ.get("VOLCENGINE_SPEECH_API_KEY", "").strip())


def _full_request(session_id: str) -> bytes:
    payload = gzip.compress(
        json.dumps(
            {
                "user": {"uid": session_id},
                "audio": {
                    "format": "pcm",
                    "codec": "raw",
                    "rate": ASR_SAMPLE_RATE,
                    "bits": 16,
                    "channel": 1,
                    "language": "zh-CN",
                },
                "request": {
                    "model_name": "bigmodel",
                    "enable_nonstream": True,
                    "enable_itn": True,
                    "enable_punc": True,
                    "enable_ddc": False,
                    "show_utterances": True,
                    "end_window_size": 600,
                    "force_to_speech_time": 400,
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    header = bytes((0x11, 0x10, 0x11, 0x00))
    return header + struct.pack(">I", len(payload)) + payload


def _audio_request(pcm: bytes, *, final: bool = False) -> bytes:
    compressed = gzip.compress(pcm)
    flags = 0x02 if final else 0x00
    header = bytes((0x11, 0x20 | flags, 0x01, 0x00))
    return header + struct.pack(">I", len(compressed)) + compressed


def parse_response(message: bytes) -> dict:
    if not isinstance(message, bytes) or len(message) < 8:
        raise RuntimeError("Volcengine ASR returned an invalid frame")
    header_size = (message[0] & 0x0F) * 4
    message_type = message[1] >> 4
    flags = message[1] & 0x0F
    serialization = message[2] >> 4
    compression = message[2] & 0x0F
    offset = header_size

    if message_type == 0x09:
        if flags & 0x01:
            if len(message) < offset + 4:
                raise RuntimeError("Volcengine ASR response omitted its sequence")
            offset += 4
        if len(message) < offset + 4:
            raise RuntimeError("Volcengine ASR response omitted its payload size")
        size = struct.unpack(">I", message[offset : offset + 4])[0]
        payload = message[offset + 4 : offset + 4 + size]
        if len(payload) != size:
            raise RuntimeError("Volcengine ASR returned a truncated payload")
        if compression == 0x01:
            payload = gzip.decompress(payload)
        if serialization != 0x01:
            return {}
        try:
            parsed = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Volcengine ASR returned invalid JSON") from exc
        return parsed if isinstance(parsed, dict) else {}

    if message_type == 0x0F:
        if len(message) < offset + 8:
            raise RuntimeError("Volcengine ASR returned an invalid error frame")
        code = struct.unpack(">I", message[offset : offset + 4])[0]
        size = struct.unpack(">I", message[offset + 4 : offset + 8])[0]
        detail = message[offset + 8 : offset + 8 + size].decode(
            "utf-8", errors="replace"
        )
        raise RuntimeError(f"Volcengine ASR error {code}: {detail[:300]}")

    return {}


def final_utterances(event: dict) -> list[dict]:
    result = event.get("result") or {}
    utterances = result.get("utterances") or []
    return [
        utterance
        for utterance in utterances
        if isinstance(utterance, dict)
        and utterance.get("definite") is True
        and str(utterance.get("text") or "").strip()
    ]


class StreamingASR:
    def __init__(self, websocket) -> None:
        self.websocket = websocket
        self._closed = False

    @classmethod
    async def connect(cls, session_id: str) -> "StreamingASR":
        api_key = os.environ.get("VOLCENGINE_SPEECH_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("Volcengine Speech API key is not configured")

        import websockets

        parameters = inspect.signature(websockets.connect).parameters
        header_name = (
            "additional_headers"
            if "additional_headers" in parameters
            else "extra_headers"
        )
        websocket = await websockets.connect(
            ASR_URL,
            **{
                header_name: {
                    "X-Api-Key": api_key,
                    "X-Api-Resource-Id": ASR_RESOURCE_ID,
                    "X-Api-Request-Id": str(uuid.uuid4()),
                    "X-Api-Sequence": "-1",
                },
                "max_size": 2 * 1024 * 1024,
                "open_timeout": 15,
            },
        )
        client = cls(websocket)
        await websocket.send(_full_request(session_id))
        return client

    async def send_audio(self, pcm: bytes) -> None:
        if self._closed:
            raise RuntimeError("Volcengine ASR session is closed")
        if not pcm or len(pcm) % 2:
            raise ValueError("ASR audio must be aligned PCM16")
        await self.websocket.send(_audio_request(pcm))

    async def events(self) -> AsyncIterator[dict]:
        async for message in self.websocket:
            if isinstance(message, str):
                message = message.encode("latin-1")
            event = parse_response(message)
            if event:
                yield event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self.websocket.send(_audio_request(b"", final=True))
        except Exception:
            pass
        await self.websocket.close()
