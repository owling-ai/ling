from __future__ import annotations

import base64
import json

import pytest

from backend import child_tts


class _Response:
    def __init__(self, lines: list[bytes]) -> None:
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def __iter__(self):
        return iter(self.lines)


def test_synthesize_pcm_uses_server_allowlisted_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def open_fake(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(
            [
                json.dumps(
                    {"code": 20_000_000, "data": base64.b64encode(b"pcm-").decode()}
                ).encode()
                + b"\n",
                json.dumps(
                    {"code": 0, "data": base64.b64encode(b"audio").decode()}
                ).encode()
                + b"\n",
            ]
        )

    monkeypatch.setenv("VOLCENGINE_SPEECH_API_KEY", "secret-key")
    monkeypatch.setattr(child_tts.urllib.request, "urlopen", open_fake)

    assert child_tts.synthesize_pcm("  你好   小朋友  ", "sprout") == b"pcm-audio"

    request = captured["request"]
    body = json.loads(request.data)
    assert body["req_params"]["text"] == "你好 小朋友"
    assert body["req_params"]["speaker"] == "ICL_uranus_zh_female_jiaxiaozi_tob"
    assert body["req_params"]["audio_params"] == {
        "format": "pcm",
        "sample_rate": 24000,
        "speech_rate": 0,
    }
    assert body["req_params"]["context_texts"]
    headers = dict(request.header_items())
    assert headers["X-api-key"] == "secret-key"
    assert headers["X-api-resource-id"] == "seed-tts-2.0"
    assert captured["timeout"] == child_tts.TTS_TIMEOUT_SECONDS


def test_synthesize_pcm_requires_server_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOLCENGINE_SPEECH_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="API key"):
        child_tts.synthesize_pcm("你好")
