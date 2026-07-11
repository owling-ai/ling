from __future__ import annotations

import asyncio
import json

import pytest

from backend import engine, realtime, voice_profiles


class _RejectedConnection(Exception):
    def __init__(self, status_code: int):
        self.response = type("Response", (), {"status_code": status_code})()


@pytest.mark.parametrize(
    ("status_code", "code", "message", "retryable"),
    [
        (401, "provider_auth_failed", "StepFun 鉴权失败，请检查 API Key 和模型权限", False),
        (402, "provider_quota_exceeded", "StepFun API 额度不足，请检查套餐与账单", False),
        (404, "provider_not_found", "StepFun 实时模型或接口不存在，请检查模型配置", False),
        (429, "provider_rate_limited", "StepFun 请求过于频繁，请稍后再试", True),
        (503, "provider_unavailable", "StepFun 服务暂时不可用，请稍后再试", True),
    ],
)
def test_provider_error_event_translates_http_status(
    status_code: int,
    code: str,
    message: str,
    retryable: bool,
) -> None:
    event = realtime._provider_error_event("stepfun", _RejectedConnection(status_code))

    assert event == {
        "type": "ling.error",
        "code": code,
        "message": message,
        "provider": "stepfun",
        "retryable": retryable,
    }


def test_gemini_setup_and_history_recovery_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(realtime, "_system_instruction", lambda _pack: "system")

    setup = realtime._gemini_setup(
        {}, resumption_handle="handle-1", initial_history=True
    )["setup"]

    assert setup["sessionResumption"] == {"handle": "handle-1"}
    assert setup["historyConfig"] == {"initialHistoryInClientContent": True}
    assert setup["contextWindowCompression"] == {"slidingWindow": {}}

    message = realtime._gemini_history_message(
        [
            {"role": "user", "content": "我喜欢恐龙"},
            {"role": "assistant", "content": "我也喜欢"},
        ]
    )
    assert message == {
        "clientContent": {
            "turns": [
                {"role": "user", "parts": [{"text": "我喜欢恐龙"}]},
                {"role": "model", "parts": [{"text": "我也喜欢"}]},
            ],
            "turnComplete": True,
        }
    }


def test_open_gemini_replays_history_only_without_resumption_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Upstream:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self.closed = False

        async def send(self, raw: str) -> None:
            self.sent.append(raw)

        async def recv(self) -> str:
            return json.dumps({"setupComplete": {}})

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(realtime, "_system_instruction", lambda _pack: "system")
    upstream = Upstream()

    async def connect(*_args, **_kwargs):
        return upstream

    monkeypatch.setattr(realtime, "_connect", connect)
    history = [{"role": "user", "content": "我喜欢恐龙"}]

    opened = asyncio.run(realtime._open_gemini("missing", {}, history, None))
    assert opened is upstream
    setup = json.loads(upstream.sent[0])["setup"]
    assert setup["sessionResumption"] == {}
    assert setup["historyConfig"] == {"initialHistoryInClientContent": True}
    assert json.loads(upstream.sent[1]) == realtime._gemini_history_message(history)

    upstream.sent.clear()
    opened = asyncio.run(
        realtime._open_gemini("missing", {}, history, "handle-1")
    )
    assert opened is upstream
    setup = json.loads(upstream.sent[0])["setup"]
    assert setup["sessionResumption"] == {"handle": "handle-1"}
    assert len(upstream.sent) == 1


def test_gemini_cancel_suppresses_late_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def __init__(self) -> None:
            self.incoming = asyncio.Queue()
            self.messages: list[dict] = []
            self.done = asyncio.Event()

        async def receive_text(self) -> str:
            event = await self.incoming.get()
            if event is None:
                raise RuntimeError("client closed")
            return json.dumps(event)

        async def send_text(self, raw: str) -> None:
            event = json.loads(raw)
            self.messages.append(event)
            if event.get("type") == "response.done":
                self.done.set()

        async def close(self) -> None:
            return None

    class Upstream:
        def __init__(self) -> None:
            self.incoming = asyncio.Queue()
            self.output_sent = False

        async def send(self, raw: str) -> None:
            event = json.loads(raw)
            if "realtimeInput" in event and not self.output_sent:
                self.output_sent = True
                await self.incoming.put(
                    {
                        "serverContent": {
                            "modelTurn": {
                                "parts": [{"inlineData": {"data": "YQ=="}}]
                            },
                            "outputTranscription": {"text": "你好"},
                        }
                    }
                )

        def __aiter__(self):
            return self

        async def __anext__(self) -> str:
            event = await self.incoming.get()
            if event is None:
                raise StopAsyncIteration
            return json.dumps(event)

        async def close(self) -> None:
            await self.incoming.put(None)

    client = Client()
    upstream = Upstream()

    async def open_fake(*_args, **_kwargs):
        return upstream

    monkeypatch.setattr(realtime, "_open_gemini", open_fake)

    async def run() -> None:
        task = asyncio.create_task(realtime._bridge_gemini(client, "session", {}))
        await asyncio.sleep(0.05)
        await client.incoming.put(
            {"type": "input_audio_buffer.append", "audio": "AAA="}
        )
        for _ in range(50):
            await asyncio.sleep(0.01)
            if any(
                event.get("type") == "response.audio.delta"
                for event in client.messages
            ):
                break
        assert any(
            event.get("type") == "response.audio.delta"
            for event in client.messages
        )

        await client.incoming.put({"type": "response.cancel"})
        await asyncio.wait_for(client.done.wait(), timeout=1)
        audio_count = sum(
            event.get("type") == "response.audio.delta" for event in client.messages
        )
        await upstream.incoming.put(
            {
                "serverContent": {
                    "modelTurn": {
                        "parts": [{"inlineData": {"data": "Yg=="}}]
                    },
                    "outputTranscription": {"text": "迟到"},
                    "turnComplete": True,
                }
            }
        )
        await asyncio.sleep(0.05)
        assert sum(
            event.get("type") == "response.audio.delta" for event in client.messages
        ) == audio_count
        await client.incoming.put(None)
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(run())


def test_bridge_reports_stepfun_quota_instead_of_exception_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def __init__(self) -> None:
            self.messages: list[dict] = []
            self.accepted = False
            self.closed = False

        async def accept(self) -> None:
            self.accepted = True

        async def send_text(self, raw: str) -> None:
            self.messages.append(json.loads(raw))

        async def close(self) -> None:
            self.closed = True

    async def reject_stepfun(*_args, **_kwargs) -> None:
        raise _RejectedConnection(402)

    monkeypatch.setenv("STEPFUN_API_KEY", "test-key")
    monkeypatch.setattr(engine, "get_session", lambda _session_id: {"pack": {}})
    monkeypatch.setattr(realtime, "_bridge_stepfun", reject_stepfun)
    client = Client()

    asyncio.run(realtime.bridge(client, "test-session", "stepfun"))

    assert client.accepted is True
    assert client.closed is True
    assert client.messages == [
        {
            "type": "ling.error",
            "code": "provider_quota_exceeded",
            "message": "StepFun API 额度不足，请检查套餐与账单",
            "provider": "stepfun",
            "retryable": False,
        }
    ]


def test_gemini_child_rtc_is_the_default_when_hybrid_callback_is_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LING_REALTIME_PROVIDER", "gemini")
    monkeypatch.setattr(realtime, "VOLC_USES_GEMINI", True)
    monkeypatch.setattr(realtime, "provider_available", lambda name: name != "minicpm")

    assert realtime.default_provider() == "volcengine"


def test_child_voice_profiles_expose_only_bundled_safe_choices() -> None:
    profiles = voice_profiles.public_voice_profiles()

    assert [profile["id"] for profile in profiles] == ["sunny", "sprout"]
    assert all(profile["preview_url"].endswith(".wav") for profile in profiles)
    assert all("voice" not in profile for profile in profiles)
    assert all("resource_id" not in profile for profile in profiles)
    assert all("style_instruction" not in profile for profile in profiles)


def test_child_voice_profile_resolver_falls_back_to_sunny() -> None:
    assert voice_profiles.resolve_voice_profile("sprout")["voice"] == (
        "ICL_uranus_zh_female_jiaxiaozi_tob"
    )
    assert voice_profiles.resolve_voice_profile("not-a-profile")["id"] == "sunny"


def test_native_gemini_setup_uses_only_legacy_prebuilt_voice() -> None:
    pack = {"doll_card": {"name": "灵灵"}, "child_card": {"name": "悠悠"}}

    setup = realtime._gemini_setup(pack)["setup"]
    voice = setup["generationConfig"]["speechConfig"]["voiceConfig"]
    instruction = setup["systemInstruction"]["parts"][0]["text"]

    assert voice == {"prebuiltVoiceConfig": {"voiceName": realtime.GEMINI_VOICE}}
    assert "固定声音角色" not in instruction


def test_realtime_info_publishes_one_gemini_entry_without_upstream_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(realtime, "hybrid_gemini_available", lambda: True)
    info = realtime.info()

    assert "gemini" not in info["providers"]
    assert info["providers"]["volcengine"]["label"] == "Gemini"
    assert info["providers"]["volcengine"]["short_label"] == "Gemini"
    assert "model" not in info
    assert "voice" not in info
    assert all("model" not in provider for provider in info["providers"].values())
    assert all("voice" not in provider for provider in info["providers"].values())
    assert info["default_voice_profile"] in {
        profile["id"] for profile in info["voice_profiles"]
    }
    assert info["providers"]["volcengine"]["voice_profile"] == info[
        "default_voice_profile"
    ]
