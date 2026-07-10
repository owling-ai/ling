"""StepFun Realtime 与 Gemini Live 双提供商语音代理。

浏览器只使用一套 OpenAI Realtime 风格的内部事件协议；本模块按 provider 把它转换成
StepFun 或 Gemini Live 的上游协议。API key 始终只存在于后端。
"""
import asyncio
import json
import os
import re
import sys
import uuid

from . import engine, prompts

STEPFUN_URL = os.environ.get("LING_STEPFUN_URL", "wss://api.stepfun.com/v1/realtime")
STEPFUN_MODEL = os.environ.get("LING_STEPFUN_MODEL", "stepaudio-2.5-realtime")
STEPFUN_VOICE = os.environ.get("LING_STEPFUN_VOICE", "linjiajiejie")
STEPFUN_SILENCE_MS = int(os.environ.get("LING_STEPFUN_SILENCE_MS", "600"))

GEMINI_URL = os.environ.get(
    "LING_GEMINI_LIVE_URL",
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent",
)
GEMINI_MODEL = os.environ.get(
    "LING_GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-latest"
)
GEMINI_VOICE = os.environ.get("LING_GEMINI_VOICE", "Aoede")
GEMINI_SILENCE_MS = int(os.environ.get("LING_GEMINI_SILENCE_MS", "600"))

PROVIDER_INFO = {
    "stepfun": {
        "model": STEPFUN_MODEL,
        "voice": STEPFUN_VOICE,
        "input_sample_rate": 24000,
        "output_sample_rate": 24000,
    },
    "gemini": {
        "model": GEMINI_MODEL,
        "voice": GEMINI_VOICE,
        "input_sample_rate": 16000,
        "output_sample_rate": 24000,
    },
}

STEPFUN_CLIENT_EVENTS = {
    "input_audio_buffer.append",
    "input_audio_buffer.commit",
    "input_audio_buffer.clear",
    "response.create",
    "response.cancel",
    "conversation.item.create",
}

VOICE_NOTE = """

# 语音通话模式（重要）
现在孩子正在跟你打语音电话，你说的话会直接变成声音读出来：
- 每次回复 1-2 句，短句、纯口语，像说话不像写字。
- 禁止 emoji、括号动作、任何念不出来的符号。
- 可以用「嘿嘿」「唔——」这类语气词，让自己听起来是活的。

# 再钉一遍（最重要）
先听懂孩子这一句要什么，就答什么。孩子让你聊他的事、说他学的词、或说「别说你的」，
立刻照办，绝不绕回你自己的话题或预设复习词。复习词可有可无，孩子的当下需求是唯一主线。"""


def provider_available(provider: str) -> bool:
    if provider == "gemini":
        return bool(os.environ.get("GEMINI_API_KEY"))
    if provider == "stepfun":
        return bool(os.environ.get("STEPFUN_API_KEY"))
    return False


def default_provider() -> str:
    configured = os.environ.get("LING_REALTIME_PROVIDER", "").lower()
    if configured in PROVIDER_INFO and provider_available(configured):
        return configured
    if provider_available("gemini"):
        return "gemini"
    if provider_available("stepfun"):
        return "stepfun"
    return configured if configured in PROVIDER_INFO else "gemini"


def available(provider: str | None = None) -> bool:
    if provider:
        return provider_available(provider)
    return any(provider_available(name) for name in PROVIDER_INFO)


def info() -> dict:
    providers = {
        name: {**config, "available": provider_available(name)}
        for name, config in PROVIDER_INFO.items()
    }
    selected = default_provider()
    current = providers[selected]
    return {
        "available": available(),
        "default_provider": selected,
        "providers": providers,
        "model": current["model"],
        "voice": current["voice"],
        "sample_rate": current["input_sample_rate"],
        "input_sample_rate": current["input_sample_rate"],
        "output_sample_rate": current["output_sample_rate"],
    }


def _log(msg: str):
    print(f"[realtime] {msg}", file=sys.stderr, flush=True)


def _normalize_transcript(text: str) -> str:
    """Gemini 的流式中文 ASR/TTS 转写偶尔会在汉字间插入空格。"""
    return re.sub(
        r"(?<=[\u3400-\u9fff，。！？、；：])\s+(?=[\u3400-\u9fff，。！？、；：])",
        "",
        text.strip(),
    )


async def _connect(url: str, headers: dict[str, str]):
    import websockets

    try:  # websockets >= 14
        return await websockets.connect(
            url, additional_headers=headers, max_size=None, open_timeout=15
        )
    except TypeError:  # websockets 12-13
        return await websockets.connect(
            url, extra_headers=headers, max_size=None, open_timeout=15
        )


async def _send_json(client, obj: dict):
    await client.send_text(json.dumps(obj, ensure_ascii=False))


def _system_instruction(pack: dict) -> str:
    return prompts.build_doll_system(pack) + VOICE_NOTE


def _stepfun_session_update(pack: dict) -> str:
    return json.dumps(
        {
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "instructions": _system_instruction(pack),
                "voice": STEPFUN_VOICE,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "turn_detection": {
                    "type": "server_vad",
                    "prefix_padding_ms": 500,
                    "silence_duration_ms": STEPFUN_SILENCE_MS,
                },
            },
        },
        ensure_ascii=False,
    )


async def _bridge_stepfun(client, session_id: str, pack: dict):
    headers = {"Authorization": f"Bearer {os.environ['STEPFUN_API_KEY']}"}
    upstream = await _connect(f"{STEPFUN_URL}?model={STEPFUN_MODEL}", headers)
    await upstream.send(_stepfun_session_update(pack))
    await upstream.send(json.dumps({"type": "response.create"}))
    _log(
        f"已接通 StepFun · {STEPFUN_MODEL} · voice={STEPFUN_VOICE} · "
        f"session={session_id}"
    )

    partial: dict[str, list[str]] = {}
    recorded: set[str] = set()

    async def push_state(state: dict | None):
        if state:
            await _send_json(client, {"type": "ling.state", **state})

    def record_doll(response_id: str, text: str):
        if not response_id or response_id in recorded:
            return None
        recorded.add(response_id)
        partial.pop(response_id, None)
        return engine.record_voice_doll(session_id, text)

    async def pump_up():
        while True:
            raw = await client.receive_text()
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if event.get("type") not in STEPFUN_CLIENT_EVENTS:
                continue
            if event.get("type") == "conversation.item.create":
                for part in (event.get("item") or {}).get("content") or []:
                    if part.get("type") in ("input_text", "text") and part.get("text"):
                        engine.record_voice_user(session_id, part["text"])
            await upstream.send(raw)

    async def pump_down():
        async for raw in upstream:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            event_type = event.get("type")
            if event_type == "conversation.item.input_audio_transcription.completed":
                engine.record_voice_user(session_id, event.get("transcript") or "")
            elif event_type == "response.audio_transcript.delta":
                partial.setdefault(event.get("response_id") or "", []).append(
                    event.get("delta") or ""
                )
            elif event_type == "response.audio_transcript.done":
                state = record_doll(
                    event.get("response_id") or "", event.get("transcript") or ""
                )
                await client.send_text(raw)
                await push_state(state)
                continue
            elif event_type == "response.done":
                response = event.get("response") or {}
                response_id = response.get("id") or ""
                if response_id and response_id not in recorded:
                    text = "".join(partial.get(response_id) or [])
                    if not text:
                        text = " ".join(
                            part.get("transcript") or part.get("text") or ""
                            for item in response.get("output") or []
                            for part in item.get("content") or []
                        ).strip()
                    state = record_doll(response_id, text)
                    await client.send_text(raw)
                    await push_state(state)
                    continue
            elif event_type == "error":
                _log(f"StepFun error：{event.get('code')} {event.get('message')}")
            await client.send_text(raw)

    await _run_pumps(client, upstream, pump_up, pump_down)


def _gemini_setup(pack: dict) -> dict:
    model = GEMINI_MODEL if GEMINI_MODEL.startswith("models/") else f"models/{GEMINI_MODEL}"
    return {
        "setup": {
            "model": model,
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": GEMINI_VOICE}
                    }
                },
            },
            "systemInstruction": {"parts": [{"text": _system_instruction(pack)}]},
            "realtimeInputConfig": {
                "automaticActivityDetection": {
                    "disabled": False,
                    "prefixPaddingMs": 500,
                    "silenceDurationMs": GEMINI_SILENCE_MS,
                }
            },
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
        }
    }


async def _bridge_gemini(client, session_id: str, pack: dict):
    upstream = await _connect(
        GEMINI_URL, {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}
    )
    await upstream.send(json.dumps(_gemini_setup(pack), ensure_ascii=False))
    first = json.loads(await asyncio.wait_for(upstream.recv(), timeout=20))
    if "setupComplete" not in first:
        raise RuntimeError((first.get("error") or {}).get("message", "Gemini setup 失败"))

    await _send_json(client, {"type": "session.created", "provider": "gemini"})
    await upstream.send(
        json.dumps(
            {
                "clientContent": {
                    "turns": [
                        {
                            "role": "user",
                            "parts": [
                                {
                                    "text": "现在通话刚接通。请根据记忆钩子主动用一句简短、自然的话和孩子打招呼。"
                                }
                            ],
                        }
                    ],
                    "turnComplete": True,
                }
            },
            ensure_ascii=False,
        )
    )
    _log(
        f"已接通 Gemini Live · {GEMINI_MODEL} · voice={GEMINI_VOICE} · "
        f"session={session_id}"
    )

    response_id = ""
    response_open = False
    output_text: list[str] = []
    input_text: list[str] = []
    input_pending = False

    async def ensure_response():
        nonlocal response_id, response_open, output_text
        if response_open:
            return
        response_id = f"gemini-{uuid.uuid4().hex}"
        response_open = True
        output_text = []
        await _send_json(
            client,
            {"type": "response.created", "id": response_id, "response": {"id": response_id}},
        )

    async def flush_input():
        nonlocal input_text, input_pending
        text = _normalize_transcript("".join(input_text))
        if not input_pending and not text:
            return
        if text:
            engine.record_voice_user(session_id, text)
        await _send_json(
            client,
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": text,
            },
        )
        input_text = []
        input_pending = False

    async def finish_response():
        nonlocal response_id, response_open, output_text
        if not response_open:
            return
        text = _normalize_transcript("".join(output_text))
        if text:
            await _send_json(
                client,
                {
                    "type": "response.audio_transcript.done",
                    "response_id": response_id,
                    "transcript": text,
                },
            )
        state = engine.record_voice_doll(session_id, text) if text else None
        await _send_json(
            client, {"type": "response.done", "response": {"id": response_id}}
        )
        if state:
            await _send_json(client, {"type": "ling.state", **state})
        response_id = ""
        response_open = False
        output_text = []

    async def pump_up():
        while True:
            raw = await client.receive_text()
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            event_type = event.get("type")
            if event_type == "input_audio_buffer.append" and event.get("audio"):
                await upstream.send(
                    json.dumps(
                        {
                            "realtimeInput": {
                                "audio": {
                                    "data": event["audio"],
                                    "mimeType": "audio/pcm;rate=16000",
                                }
                            }
                        }
                    )
                )
            elif event_type == "conversation.item.create":
                texts = [
                    part.get("text", "")
                    for part in (event.get("item") or {}).get("content") or []
                    if part.get("type") in ("input_text", "text") and part.get("text")
                ]
                text = " ".join(texts).strip()
                if text:
                    engine.record_voice_user(session_id, text)
                    await upstream.send(
                        json.dumps(
                            {
                                "clientContent": {
                                    "turns": [
                                        {"role": "user", "parts": [{"text": text}]}
                                    ],
                                    "turnComplete": True,
                                }
                            },
                            ensure_ascii=False,
                        )
                    )

    async def pump_down():
        nonlocal input_pending
        async for raw in upstream:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if event.get("error"):
                error = event["error"]
                _log(f"Gemini error：{error.get('code')} {error.get('message')}")
                await _send_json(client, {"type": "error", **error})
                continue

            content = event.get("serverContent") or {}
            transcription = content.get("inputTranscription") or {}
            if transcription.get("text"):
                if not input_pending:
                    input_pending = True
                    await _send_json(client, {"type": "input_audio_buffer.speech_stopped"})
                input_text.append(transcription["text"])

            model_turn = content.get("modelTurn") or {}
            parts = model_turn.get("parts") or []
            output_transcription = content.get("outputTranscription") or {}
            has_output = bool(parts or output_transcription.get("text"))
            if has_output:
                await flush_input()
                await ensure_response()

            for part in parts:
                inline_data = part.get("inlineData") or {}
                if inline_data.get("data"):
                    await _send_json(
                        client,
                        {"type": "response.audio.delta", "delta": inline_data["data"]},
                    )

            if output_transcription.get("text"):
                delta = output_transcription["text"]
                output_text.append(delta)
                await _send_json(
                    client,
                    {
                        "type": "response.audio_transcript.delta",
                        "response_id": response_id,
                        "delta": delta,
                    },
                )

            if content.get("interrupted"):
                await _send_json(client, {"type": "input_audio_buffer.speech_started"})
                await finish_response()
            if content.get("turnComplete"):
                await flush_input()
                await finish_response()

    await _run_pumps(client, upstream, pump_up, pump_down)


async def _run_pumps(client, upstream, pump_up, pump_down):
    up = asyncio.create_task(pump_up())
    down = asyncio.create_task(pump_down())
    try:
        done, _ = await asyncio.wait(
            {up, down}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in done:
            if not task.cancelled():
                task.exception()
    finally:
        for task in (up, down):
            task.cancel()
        try:
            await upstream.close()
        except Exception:
            pass
        try:
            await client.close()
        except Exception:
            pass


async def bridge(client, session_id: str, provider: str | None = None):
    """浏览器与指定实时模型之间的双向代理，并把转写写入记忆引擎。"""
    await client.accept()
    provider = (provider or default_provider()).lower()
    if provider not in PROVIDER_INFO:
        await _send_json(client, {"type": "ling.error", "message": "不支持的实时模型"})
        await client.close()
        return
    if not provider_available(provider):
        env_name = "GEMINI_API_KEY" if provider == "gemini" else "STEPFUN_API_KEY"
        await _send_json(
            client,
            {"type": "ling.error", "message": f"没设 {env_name}，{provider} 不可用"},
        )
        await client.close()
        return
    session = engine.get_session(session_id)
    if not session:
        await _send_json(client, {"type": "ling.error", "message": "会话不存在，请先开始会话"})
        await client.close()
        return

    try:
        if provider == "gemini":
            await _bridge_gemini(client, session_id, session["pack"])
        else:
            await _bridge_stepfun(client, session_id, session["pack"])
    except Exception as exc:
        _log(f"连接 {provider} 失败：{type(exc).__name__}: {exc}")
        try:
            await _send_json(
                client,
                {"type": "ling.error", "message": f"连不上 {provider}：{type(exc).__name__}"},
            )
            await client.close()
        except Exception:
            pass
    finally:
        _log(f"通话结束 · provider={provider} · session={session_id}")
