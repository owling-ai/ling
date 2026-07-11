from __future__ import annotations

import asyncio
import base64
import json
import struct

import pytest

from backend import realtime


class FakeClient:
    def __init__(self, incoming: list[dict]):
        self.incoming = [json.dumps(event) for event in incoming]
        self.sent: list[dict] = []
        self.closed = False

    async def receive_text(self) -> str:
        if self.incoming:
            return self.incoming.pop(0)
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def send_text(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def close(self) -> None:
        self.closed = True


class FakeUpstream:
    def __init__(self, downstream: list[dict]):
        self.handshake = [
            {"type": "session.queue_done"},
            {"type": "session.created", "session_id": "upstream-session"},
        ]
        self.downstream = list(downstream)
        self.sent: list[dict] = []
        self.input_ready = asyncio.Event()
        self.closed = False

    async def recv(self) -> str:
        return json.dumps(self.handshake.pop(0))

    async def send(self, raw: str) -> None:
        event = json.loads(raw)
        self.sent.append(event)
        if event.get("type") == "input.append":
            self.input_ready.set()

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        await self.input_ready.wait()
        if not self.downstream:
            raise StopAsyncIteration
        return json.dumps(self.downstream.pop(0))

    async def close(self) -> None:
        self.closed = True


def _pcm16_b64(sample: int, count: int) -> str:
    raw = sample.to_bytes(2, "little", signed=True) * count
    return base64.b64encode(raw).decode("ascii")


def test_minicpm_endpoint_derivation_and_optional_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(realtime, "MINICPM_REALTIME_URL", "")
    monkeypatch.setattr(realtime, "MINICPM_BASE_URL", "http://192.168.1.9:9000/v1")
    monkeypatch.setattr(realtime, "MINICPM_API_KEY", "")

    assert realtime._minicpm_endpoint(False) == (
        "ws://192.168.1.9:9000/v1/realtime?mode=audio"
    )
    assert realtime._minicpm_endpoint(True) == (
        "ws://192.168.1.9:9000/v1/realtime?mode=video"
    )
    assert realtime._minicpm_headers() == {}

    monkeypatch.setattr(
        realtime,
        "MINICPM_REALTIME_URL",
        "https://model.lan/custom/realtime?region=local&mode=chat",
    )
    monkeypatch.setattr(realtime, "MINICPM_API_KEY", "test-token")
    assert realtime._minicpm_endpoint(True) == (
        "wss://model.lan/custom/realtime?region=local&mode=video"
    )
    assert realtime._minicpm_headers() == {"Authorization": "Bearer test-token"}


def test_minicpm_pcm16_float32_conversion_round_trip() -> None:
    pcm16 = struct.pack("<5h", -32768, -16384, 0, 16384, 32767)
    encoded = base64.b64encode(pcm16).decode("ascii")

    float32_encoded = realtime._pcm16_b64_to_float32_b64(encoded)
    floats = struct.unpack("<5f", base64.b64decode(float32_encoded))
    assert floats == pytest.approx((-1.0, -0.5, 0.0, 0.5, 32767 / 32768))

    converted = base64.b64decode(
        realtime._float32_b64_to_pcm16_b64(float32_encoded)
    )
    assert struct.unpack("<5h", converted) == (-32768, -16384, 0, 16384, 32767)


def test_minicpm_audio_and_video_input_payloads() -> None:
    pcm16 = struct.pack("<2h", -1000, 1000)
    frame = base64.b64encode(b"\xff\xd8jpeg\xff\xd9").decode("ascii")

    audio = realtime._minicpm_input_message(pcm16, False, frame)
    assert set(audio["input"]) == {"audio", "force_listen"}
    assert audio["input"]["force_listen"] is False

    video = realtime._minicpm_input_message(pcm16, True, frame)
    assert video["input"]["video_frames"] == [frame]
    assert video["input"]["max_slice_nums"] == 1
    assert realtime._minicpm_video_frame(
        {"mime_type": "image/jpeg", "data": frame}
    ) == frame
    assert realtime._minicpm_video_frame(
        {"mime_type": "image/png", "data": frame}
    ) is None


def test_minicpm_bridge_waits_for_queue_and_translates_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = base64.b64encode(b"\xff\xd8frame\xff\xd9").decode("ascii")
    input_events = [
        {"type": "ling.video_frame", "mime_type": "image/jpeg", "data": frame},
        *[
            {
                "type": "input_audio_buffer.append",
                "audio": _pcm16_b64(8192, 1600),
            }
            for _ in range(10)
        ],
    ]
    output_audio = base64.b64encode(struct.pack("<3f", -1.0, 0.0, 0.5)).decode(
        "ascii"
    )
    upstream = FakeUpstream(
        [
            {
                "type": "response.output.delta",
                "kind": "text",
                "response_id": "response-1",
                "text": "你好",
            },
            {
                "type": "response.output.delta",
                "kind": "audio",
                "response_id": "response-1",
                "audio": output_audio,
            },
            {"type": "response.output.delta", "kind": "listen"},
            {"type": "session.closed", "reason": "user_stop"},
        ]
    )
    client = FakeClient(input_events)
    recorded: list[tuple[str, str]] = []

    async def fake_connect(
        _url: str, _headers: dict[str, str], *, use_proxy: bool = True
    ):
        assert use_proxy is False
        return upstream

    def fake_record(session_id: str, text: str) -> dict:
        recorded.append((session_id, text))
        return {"woven": ["hello"]}

    monkeypatch.setattr(realtime, "_connect", fake_connect)
    monkeypatch.setattr(realtime, "_system_instruction", lambda _pack: "system")
    monkeypatch.setattr(realtime.engine, "record_voice_doll", fake_record)
    monkeypatch.setattr(realtime, "MINICPM_INPUT_CHUNK_MS", 1000)
    monkeypatch.setattr(realtime, "MINICPM_REALTIME_URL", "ws://model.lan/v1/realtime")

    async def run_bridge() -> None:
        await asyncio.wait_for(
            realtime._bridge_minicpm(client, "ling-session", {}, True), timeout=2
        )

    asyncio.run(run_bridge())

    assert upstream.sent[0] == {
        "type": "session.init",
        "payload": {
            "system_prompt": "system",
            "config": {"length_penalty": realtime.MINICPM_LENGTH_PENALTY},
        },
    }
    input_message = next(event for event in upstream.sent if event["type"] == "input.append")
    input_samples = struct.unpack(
        "<16000f", base64.b64decode(input_message["input"]["audio"])
    )
    assert input_samples[0] == pytest.approx(0.25)
    assert input_message["input"]["video_frames"] == [frame]
    assert upstream.sent[-1] == {"type": "session.close", "reason": "user_stop"}

    types = [event["type"] for event in client.sent]
    assert types == [
        "session.created",
        "response.created",
        "response.audio_transcript.delta",
        "response.audio.delta",
        "response.audio_transcript.done",
        "response.done",
        "ling.state",
    ]
    audio_delta = next(event for event in client.sent if event["type"] == "response.audio.delta")
    assert struct.unpack("<3h", base64.b64decode(audio_delta["delta"])) == (
        -32768,
        0,
        16384,
    )
    assert recorded == [("ling-session", "你好")]
    assert client.closed is True
    assert upstream.closed is True
