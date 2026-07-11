from __future__ import annotations

import json

import pytest

from backend import gemini_text


class _Response:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def test_generate_reply_uses_text_model_and_bounded_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def open_fake(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(
            {"choices": [{"message": {"content": "  你好，我在呢！  "}}]}
        )

    monkeypatch.setenv("GEMINI_API_KEY", "secret-key")
    monkeypatch.setattr(gemini_text.urllib.request, "urlopen", open_fake)

    reply = gemini_text.generate_reply(
        "system",
        [
            {"role": "user", "content": "上一句"},
            {"role": "assistant", "content": "上一答"},
            {"role": "tool", "content": "private"},
        ],
        prompt="开场指令",
    )

    assert reply == "你好，我在呢！"
    request = captured["request"]
    payload = json.loads(request.data)
    assert payload["model"] == gemini_text.GEMINI_TEXT_MODEL
    assert payload["stream"] is False
    assert payload["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "上一句"},
        {"role": "assistant", "content": "上一答"},
        {"role": "user", "content": "开场指令"},
    ]
    assert dict(request.header_items())["Authorization"] == "Bearer secret-key"
    assert captured["timeout"] == gemini_text.GEMINI_TEXT_TIMEOUT_SECONDS


def test_generate_reply_requires_server_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="API key"):
        gemini_text.generate_reply("system", [])
