from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from backend import engine, llm, volcengine_rtc, voice_profiles


@pytest.fixture(autouse=True)
def clear_tasks():
    volcengine_rtc.TASKS.clear()
    yield
    volcengine_rtc.TASKS.clear()


def test_prepare_binds_allowlisted_profile_and_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(volcengine_rtc, "available", lambda: True)
    monkeypatch.setattr(engine, "get_session", lambda _session_id: {"pack": {}})
    monkeypatch.setattr(
        volcengine_rtc, "create_rtc_token", lambda _room_id, _user_id: "rtc-token"
    )

    defaulted = volcengine_rtc.prepare("hardware-default")
    selected = volcengine_rtc.prepare("selected", "sprout")
    locked = volcengine_rtc.prepare("selected", "sunny")
    fallback = volcengine_rtc.prepare("fallback", "not-allowlisted")

    assert defaulted["voice_profile"] == "sunny"
    assert defaulted["voice_name"] == "小晴天"
    assert selected["voice_profile"] == "sprout"
    assert locked["voice_profile"] == "sprout"
    assert selected["voice_name"] == "小青芽"
    assert fallback["voice_profile"] == "sunny"
    assert volcengine_rtc.TASKS["selected"]["voice_profile"]["voice"] == (
        "ICL_uranus_zh_female_jiaxiaozi_tob"
    )


def test_start_payload_uses_seed_tts_profile_and_persistent_natural_style(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(volcengine_rtc.prompts, "build_doll_system", lambda _pack: "sys")
    monkeypatch.setattr(volcengine_rtc, "GEMINI_LLM_URL", "")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    profile = voice_profiles.resolve_voice_profile("sunny")
    task = {
        "room_id": "room",
        "task_id": "task",
        "user_id": "user",
        "bot_id": "bot",
        "voice_profile": profile,
    }

    payload = volcengine_rtc._start_payload(task, {})
    config = payload["Config"]
    tts = config["TTSConfig"]
    parameters = json.loads(tts["ProviderParams"]["VolcanoTTSParameters"])

    assert config["InterruptMode"] == 0
    assert config["VADConfig"] == {"SilenceTime": 600}
    assert tts["Provider"] == "volcano_bidirection"
    assert tts["ProviderParams"]["Credential"] == {"ResourceId": "seed-tts-2.0"}
    assert parameters["req_params"]["speaker"] == profile["voice"]
    assert parameters["req_params"]["context_texts"] == [
        voice_profiles.NATURAL_CHILD_STYLE
    ]
    assert "pitch" not in json.dumps(parameters)


def test_start_payload_uses_authenticated_gemini_custom_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(volcengine_rtc.prompts, "build_doll_system", lambda _pack: "sys")
    monkeypatch.setattr(
        volcengine_rtc,
        "GEMINI_LLM_URL",
        "https://ling.example/integrations/volcengine/gemini",
    )
    monkeypatch.setattr(volcengine_rtc, "GEMINI_LLM_MODEL", "gemini-test")
    monkeypatch.setenv("GEMINI_API_KEY", "private-google-key")
    task = {
        "room_id": "room",
        "task_id": "task",
        "user_id": "user",
        "bot_id": "bot",
        "voice_profile": voice_profiles.resolve_voice_profile("sprout"),
    }

    llm_config = volcengine_rtc._start_payload(task, {})["Config"]["LLMConfig"]

    assert llm_config["Mode"] == "CustomLLM"
    assert llm_config["ModelName"] == "gemini-test"
    assert llm_config["Prefill"] is True
    assert llm_config["VisionConfig"]["Enable"] is True
    assert llm_config["APIKey"] == volcengine_rtc.GEMINI_CALLBACK_TOKEN
    assert llm_config["APIKey"] != "private-google-key"


def test_gemini_openai_payload_overrides_model_and_drops_custom_data() -> None:
    source = {
        "model": "provider-model",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "你看到了什么？"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/jpeg;base64,AA=="},
                    },
                ],
            }
        ],
        "stream": False,
        "temperature": 0.3,
        "custom": "private-provider-data",
        "X-Biz-Trace-Info": "trace",
    }

    payload = volcengine_rtc._gemini_openai_payload(source)

    assert payload["model"] == volcengine_rtc.GEMINI_LLM_MODEL
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["messages"] == source["messages"]
    assert "custom" not in payload
    assert "X-Biz-Trace-Info" not in payload


def test_open_gemini_stream_retries_transient_connection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        volcengine_rtc,
        "GEMINI_LLM_URL",
        "https://ling.example/integrations/volcengine/gemini",
    )
    monkeypatch.setenv("GEMINI_API_KEY", "private-google-key")
    monkeypatch.setattr(volcengine_rtc.time, "sleep", lambda _seconds: None)
    requests = []

    def open_upstream(request, timeout):
        requests.append(request)
        assert timeout == 10
        if len(requests) == 1:
            raise volcengine_rtc.urllib.error.URLError("temporary")
        return io.BytesIO(b"data: [DONE]\n\n")

    monkeypatch.setattr(volcengine_rtc.urllib.request, "urlopen", open_upstream)

    with volcengine_rtc.open_gemini_stream({"messages": []}) as response:
        assert response.read() == b"data: [DONE]\n\n"

    assert len(requests) == 2
    assert requests[1].get_header("Authorization") == "Bearer private-google-key"


def test_prepare_route_defaults_hardware_and_allows_web_preview_selection(
    isolated_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm, "worker_live", lambda: False)
    received: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        volcengine_rtc,
        "prepare",
        lambda session_id, profile_id: received.append((session_id, profile_id))
        or {"voice_profile": profile_id},
    )
    from backend.app import app

    with TestClient(
        app,
        base_url="http://127.0.0.1:8888",
        client=("127.0.0.1", 50000),
    ) as client:
        selected = client.post(
            "/api/volcengine/prepare",
            json={"session_id": "session", "voice_profile": "sprout"},
        )
        defaulted = client.post(
            "/api/gemini/prepare",
            json={"session_id": "hardware"},
        )

    assert selected.status_code == 200
    assert defaulted.status_code == 200
    assert received == [("session", "sprout"), ("hardware", None)]


def test_gemini_callback_requires_its_ephemeral_token_and_streams_sse(
    isolated_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(llm, "worker_live", lambda: False)
    monkeypatch.setattr(
        volcengine_rtc,
        "open_gemini_stream",
        lambda _body: io.BytesIO(
            b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            b"data: [DONE]\n\n"
        ),
    )
    from backend.app import app

    with TestClient(app, client=("203.0.113.10", 50000)) as client:
        denied = client.post(
            "/integrations/volcengine/gemini",
            json={"messages": []},
        )
        accepted = client.post(
            "/integrations/volcengine/gemini",
            json={"messages": []},
            headers={
                "Authorization": f"Bearer {volcengine_rtc.GEMINI_CALLBACK_TOKEN}"
            },
        )

    assert denied.status_code == 401
    assert accepted.status_code == 200
    assert accepted.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in accepted.text
