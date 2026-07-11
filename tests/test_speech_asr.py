from __future__ import annotations

import gzip
import json
import struct

import pytest

from backend import speech_asr


def test_full_request_configures_pcm_and_server_vad() -> None:
    frame = speech_asr._full_request("session-1")

    assert frame[:4] == bytes((0x11, 0x10, 0x11, 0x00))
    size = struct.unpack(">I", frame[4:8])[0]
    payload = json.loads(gzip.decompress(frame[8 : 8 + size]))
    assert payload["user"]["uid"] == "session-1"
    assert payload["audio"] == {
        "format": "pcm",
        "codec": "raw",
        "rate": 16000,
        "bits": 16,
        "channel": 1,
        "language": "zh-CN",
    }
    assert payload["request"]["enable_nonstream"] is True
    assert payload["request"]["show_utterances"] is True
    assert payload["request"]["end_window_size"] == 600


def test_parse_response_and_extract_final_utterances() -> None:
    payload = gzip.compress(
        json.dumps(
            {
                "result": {
                    "utterances": [
                        {"start_time": 0, "end_time": 800, "text": "你好", "definite": True},
                        {"start_time": 900, "text": "还没说完", "definite": False},
                    ]
                }
            },
            ensure_ascii=False,
        ).encode()
    )
    frame = (
        bytes((0x11, 0x91, 0x11, 0x00))
        + struct.pack(">i", 1)
        + struct.pack(">I", len(payload))
        + payload
    )

    event = speech_asr.parse_response(frame)

    assert speech_asr.final_utterances(event) == [
        {"start_time": 0, "end_time": 800, "text": "你好", "definite": True}
    ]


def test_parse_response_rejects_provider_error() -> None:
    detail = b"permission denied"
    frame = (
        bytes((0x11, 0xF0, 0x10, 0x00))
        + struct.pack(">I", 45000030)
        + struct.pack(">I", len(detail))
        + detail
    )

    with pytest.raises(RuntimeError, match="45000030"):
        speech_asr.parse_response(frame)
