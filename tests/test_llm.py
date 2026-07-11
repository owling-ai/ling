from __future__ import annotations

import urllib.error

import pytest

from backend import llm


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12.5", 12.5),
        ("0", 1.0),
        ("999", 120.0),
        ("not-a-number", 60.0),
        ("nan", 60.0),
        ("inf", 60.0),
    ],
)
def test_worker_timeout_is_configurable_and_bounded(
    monkeypatch: pytest.MonkeyPatch, value: str, expected: float
) -> None:
    monkeypatch.setenv("LING_WORKER_TIMEOUT_SECONDS", value)

    assert llm._worker_timeout_seconds() == expected


def test_openai_chat_uses_longer_default_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LING_WORKER_TIMEOUT_SECONDS", raising=False)
    observed_timeouts: list[float] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return b'{"choices": [{"message": {"content": "{}"}}]}'

    def fake_urlopen(request, timeout: float):
        observed_timeouts.append(timeout)
        return Response()

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)

    result = llm._openai_chat(
        {"base": "https://example.test/v1", "key": "test-key", "model": "test-model"},
        [{"role": "user", "content": "return JSON"}],
        32,
    )

    assert result == "{}"
    assert observed_timeouts == [60.0]


def test_openai_timeout_log_includes_wait_limit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("LING_WORKER_TIMEOUT_SECONDS", raising=False)

    def fake_urlopen(request, timeout: float):
        raise urllib.error.URLError(TimeoutError("timed out"))

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)

    result = llm._openai_chat(
        {"base": "https://example.test/v1", "key": "test-key", "model": "test-model"},
        [{"role": "user", "content": "return JSON"}],
        32,
    )

    assert result is None
    assert "\u8bf7\u6c42\u8d85\u65f6\uff08\u7b49\u5f85 60 \u79d2\uff09" in capsys.readouterr().err
