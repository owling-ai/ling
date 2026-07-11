"""StepFun、Gemini Live 与 MiniCPM-o WebSocket 实时音视频代理。

浏览器只使用一套 OpenAI Realtime 风格的内部事件协议；本模块按 provider 把它转换成
各家上游协议。API key 始终只存在于后端。
"""
import asyncio
import base64
import binascii
import inspect
import json
import math
import os
import re
import sys
import uuid
from array import array
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
    "LING_GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview"
)
GEMINI_VOICE = os.environ.get("LING_GEMINI_VOICE", "Aoede")
GEMINI_SILENCE_MS = int(os.environ.get("LING_GEMINI_SILENCE_MS", "600"))
GEMINI_MAX_VIDEO_FRAME_CHARS = int(
    os.environ.get("LING_GEMINI_MAX_VIDEO_FRAME_CHARS", "1200000")
)
GEMINI_TRANSCRIPTION_LANGUAGES = [
    code.strip()
    for code in os.environ.get(
        "LING_GEMINI_TRANSCRIPTION_LANGUAGES", "zh-CN,en-US"
    ).split(",")
    if code.strip()
]

MINICPM_BASE_URL = os.environ.get("LING_MINICPM_BASE_URL", "").strip()
MINICPM_REALTIME_URL = os.environ.get("LING_MINICPM_REALTIME_URL", "").strip()
MINICPM_API_KEY = os.environ.get("LING_MINICPM_API_KEY", "").strip()
MINICPM_MODEL = os.environ.get("LING_MINICPM_MODEL", "MiniCPM-o-4.5")
MINICPM_LENGTH_PENALTY = float(
    os.environ.get("LING_MINICPM_LENGTH_PENALTY", "1.1")
)
MINICPM_INPUT_CHUNK_MS = max(
    100, int(os.environ.get("LING_MINICPM_INPUT_CHUNK_MS", "1000"))
)
MINICPM_QUEUE_TIMEOUT_SECONDS = max(
    5, int(os.environ.get("LING_MINICPM_QUEUE_TIMEOUT_SECONDS", "120"))
)
MINICPM_MAX_VIDEO_FRAME_CHARS = int(
    os.environ.get("LING_MINICPM_MAX_VIDEO_FRAME_CHARS", "1200000")
)
MINICPM_USE_PROXY = os.environ.get("LING_MINICPM_USE_PROXY", "").lower() in {
    "1",
    "true",
    "yes",
}

PROVIDER_INFO = {
    "stepfun": {
        "model": STEPFUN_MODEL,
        "voice": STEPFUN_VOICE,
        "input_sample_rate": 24000,
        "output_sample_rate": 24000,
        "supports_video": False,
    },
    "gemini": {
        "model": GEMINI_MODEL,
        "voice": GEMINI_VOICE,
        "input_sample_rate": 16000,
        "output_sample_rate": 24000,
        "supports_video": True,
    },
    "volcengine": {
        "model": os.environ.get(
            "LING_VOLC_ARK_MODEL", "doubao-seed-2-1-turbo-260628"
        ),
        "voice": os.environ.get(
            "LING_VOLC_TTS_VOICE", "zh_female_linjianvhai_moon_bigtts"
        ),
        "input_sample_rate": 48000,
        "output_sample_rate": 48000,
        "supports_video": True,
        "transport": "bytedrtc",
    },
    "minicpm": {
        "model": MINICPM_MODEL,
        "voice": "default",
        "input_sample_rate": 16000,
        "output_sample_rate": 24000,
        "supports_video": True,
        "supports_idle_nudge": False,
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
- 通话可能包含摄像头画面；只在孩子提到或画面确实有帮助时自然回应，不要持续描述画面。
- 只使用简体中文和必要的英文课程词；不要说韩文、日文，也不要把中英混合短句误当成其他语言。

# 再钉一遍（最重要）
先听懂孩子这一句要什么，就答什么。孩子让你聊他的事、说他学的词、或说「别说你的」，
立刻照办，绝不绕回你自己的话题或预设复习词。复习词可有可无，孩子的当下需求是唯一主线。"""


def provider_available(provider: str) -> bool:
    if provider == "gemini":
        return bool(os.environ.get("GEMINI_API_KEY"))
    if provider == "stepfun":
        return bool(os.environ.get("STEPFUN_API_KEY"))
    if provider == "volcengine":
        return all(
            os.environ.get(name)
            for name in (
                "VOLCENGINE_RTC_APP_ID",
                "VOLCENGINE_RTC_APP_KEY",
                "VOLCENGINE_ACCESS_KEY",
                "VOLCENGINE_SECRET_KEY",
            )
        )
    if provider == "minicpm":
        return bool(MINICPM_REALTIME_URL or MINICPM_BASE_URL)
    return False


def default_provider() -> str:
    configured = os.environ.get("LING_REALTIME_PROVIDER", "").lower()
    if configured in PROVIDER_INFO and provider_available(configured):
        return configured
    if provider_available("gemini"):
        return "gemini"
    if provider_available("stepfun"):
        return "stepfun"
    if provider_available("volcengine"):
        return "volcengine"
    if provider_available("minicpm"):
        return "minicpm"
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


def _gemini_transcription_config(pack: dict) -> dict:
    phrases = ["蜂蜜", "蜂蜜味", "橡果", "橡果味", "honey", "taste", "strong"]
    for item in pack.get("review_items") or []:
        if isinstance(item, dict):
            phrases.extend(item.get(key) for key in ("word", "zh") if item.get(key))
    share_event = pack.get("share_event") or {}
    phrases.extend(share_event.get("vocab") or [])
    for card_key in ("child_card", "doll_card"):
        name = (pack.get(card_key) or {}).get("name")
        if name:
            phrases.append(name)

    deduplicated = []
    seen = set()
    for phrase in phrases:
        phrase = str(phrase).strip()
        key = phrase.casefold()
        if phrase and key not in seen:
            seen.add(key)
            deduplicated.append(phrase)

    return {
        "languageHints": {"languageCodes": GEMINI_TRANSCRIPTION_LANGUAGES},
        "adaptationPhrases": deduplicated[:50],
    }


def _gemini_video_message(event: dict) -> dict | None:
    data = event.get("data")
    mime_type = event.get("mime_type")
    if (
        mime_type != "image/jpeg"
        or not isinstance(data, str)
        or not 0 < len(data) <= GEMINI_MAX_VIDEO_FRAME_CHARS
    ):
        return None
    return {
        "realtimeInput": {
            "video": {
                "data": data,
                "mimeType": mime_type,
            }
        }
    }


def _minicpm_endpoint(video: bool) -> str:
    """Build the realtime URL from either an explicit endpoint or an OpenAI base URL."""
    raw = MINICPM_REALTIME_URL or MINICPM_BASE_URL
    if not raw:
        raise ValueError("MiniCPM realtime URL is not configured")

    parts = urlsplit(raw)
    scheme = {"http": "ws", "https": "wss", "ws": "ws", "wss": "wss"}.get(
        parts.scheme.lower()
    )
    if not scheme or not parts.netloc:
        raise ValueError("MiniCPM URL must be an absolute http(s) or ws(s) URL")

    path = parts.path.rstrip("/")
    if MINICPM_REALTIME_URL:
        path = path or "/v1/realtime"
    elif not path:
        path = "/v1/realtime"
    elif path.endswith("/realtime"):
        pass
    elif path.endswith("/v1"):
        path += "/realtime"
    else:
        path += "/v1/realtime"

    query = [(key, value) for key, value in parse_qsl(parts.query) if key != "mode"]
    query.append(("mode", "video" if video else "audio"))
    return urlunsplit((scheme, parts.netloc, path, urlencode(query), ""))


def _minicpm_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {MINICPM_API_KEY}"} if MINICPM_API_KEY else {}


def _decode_base64(value: str, sample_width: int) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("audio payload must be non-empty base64")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("invalid base64 audio payload") from exc
    if not raw or len(raw) % sample_width:
        raise ValueError("audio payload has an invalid sample boundary")
    return raw


def _pcm16_bytes_to_float32_b64(raw: bytes) -> str:
    if not raw or len(raw) % 2:
        raise ValueError("PCM16 audio must contain complete samples")
    samples = array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    floats = array("f", (sample / 32768.0 for sample in samples))
    if sys.byteorder != "little":
        floats.byteswap()
    return base64.b64encode(floats.tobytes()).decode("ascii")


def _pcm16_b64_to_float32_b64(value: str) -> str:
    return _pcm16_bytes_to_float32_b64(_decode_base64(value, 2))


def _float32_b64_to_pcm16_b64(value: str) -> str:
    raw = _decode_base64(value, 4)
    floats = array("f")
    floats.frombytes(raw)
    if sys.byteorder != "little":
        floats.byteswap()

    def to_pcm16(sample: float) -> int:
        if not math.isfinite(sample):
            raise ValueError("float32 audio contains a non-finite sample")
        sample = max(-1.0, min(1.0, sample))
        return max(-32768, min(32767, round(sample * 32768.0)))

    samples = array("h", (to_pcm16(sample) for sample in floats))
    if sys.byteorder != "little":
        samples.byteswap()
    return base64.b64encode(samples.tobytes()).decode("ascii")


def _minicpm_video_frame(event: dict) -> str | None:
    data = event.get("data")
    if (
        event.get("mime_type") != "image/jpeg"
        or not isinstance(data, str)
        or not 0 < len(data) <= MINICPM_MAX_VIDEO_FRAME_CHARS
    ):
        return None
    try:
        raw = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error):
        return None
    if len(raw) < 4 or not raw.startswith(b"\xff\xd8") or not raw.endswith(b"\xff\xd9"):
        return None
    return data


def _minicpm_input_message(audio_pcm16: bytes, video: bool, frame: str | None) -> dict:
    payload = {
        "audio": _pcm16_bytes_to_float32_b64(audio_pcm16),
        "force_listen": False,
    }
    if video:
        if frame:
            payload["video_frames"] = [frame]
        payload["max_slice_nums"] = 1
    return {"type": "input.append", "input": payload}


async def _connect(
    url: str, headers: dict[str, str], *, use_proxy: bool = True
):
    import websockets

    parameters = inspect.signature(websockets.connect).parameters
    header_name = (
        "additional_headers" if "additional_headers" in parameters else "extra_headers"
    )
    kwargs = {
        header_name: headers,
        "max_size": None,
        "open_timeout": 15,
    }
    if not use_proxy and "proxy" in parameters:
        kwargs["proxy"] = None
    return await websockets.connect(url, **kwargs)


async def _send_json(client, obj: dict):
    await client.send_text(json.dumps(obj, ensure_ascii=False))


def _system_instruction(pack: dict) -> str:
    return prompts.build_doll_system(pack) + VOICE_NOTE


def _opening_instruction(pack: dict) -> str:
    child_name = (pack.get("child_card") or {}).get("name", "小朋友")
    doll_name = (pack.get("doll_card") or {}).get("name", "灵灵")
    return (
        f"通话刚接通。你是{doll_name}，请只用一句话向{child_name}简单打招呼，"
        f"例如『嗨，{child_name}，我在呢！』。不要提昨天、记忆、学习、待办或故事，"
        "不要问问题，不要要求孩子回答。"
    )


def _idle_instruction(pack: dict, nudge_number: int) -> str:
    child_name = (pack.get("child_card") or {}).get("name", "小朋友")
    if nudge_number == 1:
        return (
            f"这是后台冷场控制信号，不是{child_name}说的话。通话已经安静了一会儿。"
            "请结合最近对话和当前画面，用一句很短、自然的话重新建立陪伴感；可以轻轻"
            "评论眼前的事或问一个容易回答的小问题。禁止提昨天的记忆、学习议程、待办"
            "和复习词，禁止连续提问。"
        )
    return (
        f"这是本场最后一次后台冷场控制信号，不是{child_name}说的话。请优先结合当前"
        "画面或刚才的话题，用一句短话自然找回互动。只有当前话题或画面与某个复习词"
        "明显相关时，才可以像普通用词一样带出最多一个英文词；不得宣布学习、不得考试、"
        "不得强行切换话题，也不要主动追问昨天的记忆。"
    )


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
    # 不伪造用户消息；用单次 response instructions 覆盖开场，避免模型被记忆包
    # 和复习议程吸引。StepFun 会继承 session 的音频配置。
    await upstream.send(
        json.dumps(
            {
                "type": "response.create",
                "response": {"instructions": _opening_instruction(pack)},
            },
            ensure_ascii=False,
        )
    )
    _log(
        f"已接通 StepFun · {STEPFUN_MODEL} · voice={STEPFUN_VOICE} · "
        f"session={session_id}"
    )

    partial: dict[str, list[str]] = {}
    recorded: set[str] = set()
    idle_item_ready = asyncio.Event()
    waiting_for_idle_item = False

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
        nonlocal waiting_for_idle_item
        while True:
            raw = await client.receive_text()
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            event_type = event.get("type")
            if event_type == "ling.idle_nudge":
                nudge_number = engine.claim_idle_nudge(session_id)
                if nudge_number:
                    idle_item_ready.clear()
                    waiting_for_idle_item = True
                    await upstream.send(
                        json.dumps(
                            {
                                "type": "conversation.item.create",
                                "item": {
                                    "type": "message",
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "input_text",
                                            "text": _idle_instruction(pack, nudge_number),
                                        }
                                    ],
                                },
                            },
                            ensure_ascii=False,
                        )
                    )
                    try:
                        await asyncio.wait_for(idle_item_ready.wait(), timeout=2)
                        await upstream.send(json.dumps({"type": "response.create"}))
                    except asyncio.TimeoutError:
                        _log("StepFun 冷场控制消息确认超时")
                    finally:
                        waiting_for_idle_item = False
                continue
            if event_type not in STEPFUN_CLIENT_EVENTS:
                continue
            if event_type == "conversation.item.create":
                for part in (event.get("item") or {}).get("content") or []:
                    if part.get("type") in ("input_text", "text") and part.get("text"):
                        engine.record_voice_user(session_id, part["text"])
            await upstream.send(raw)

    async def pump_down():
        nonlocal waiting_for_idle_item
        async for raw in upstream:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            event_type = event.get("type")
            if event_type == "conversation.item.created" and waiting_for_idle_item:
                idle_item_ready.set()
                continue
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
    transcription = _gemini_transcription_config(pack)
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
            "inputAudioTranscription": transcription,
            "outputAudioTranscription": transcription,
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
                                    "text": _opening_instruction(pack)
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
            elif event_type == "ling.video_frame":
                message = _gemini_video_message(event)
                if message:
                    await upstream.send(json.dumps(message))
            elif event_type == "ling.idle_nudge":
                nudge_number = engine.claim_idle_nudge(session_id)
                if nudge_number:
                    await upstream.send(
                        json.dumps(
                            {
                                "clientContent": {
                                    "turns": [
                                        {
                                            "role": "user",
                                            "parts": [
                                                {
                                                    "text": _idle_instruction(
                                                        pack, nudge_number
                                                    )
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
                # 输入 ASR 可能在模型开始输出后仍继续到达；等 turnComplete 再一次性提交，
                # 避免把孩子的一句话拆成多个不完整气泡。
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


async def _receive_minicpm_event(upstream) -> dict:
    raw = await asyncio.wait_for(
        upstream.recv(), timeout=MINICPM_QUEUE_TIMEOUT_SECONDS
    )
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    event = json.loads(raw)
    if not isinstance(event, dict):
        raise RuntimeError("MiniCPM returned a non-object event")
    return event


async def _initialize_minicpm(upstream, client, pack: dict, video: bool) -> None:
    initialized = False
    while True:
        event = await _receive_minicpm_event(upstream)
        event_type = event.get("type")
        if event_type in {"session.queued", "session.queue_update"}:
            await _send_json(
                client,
                {
                    "type": "ling.queue",
                    "position": event.get("position"),
                    "estimated_wait_s": event.get("estimated_wait_s"),
                },
            )
        elif event_type == "session.queue_done":
            await upstream.send(
                json.dumps(
                    {
                        "type": "session.init",
                        "payload": {
                            "system_prompt": _system_instruction(pack),
                            "config": {"length_penalty": MINICPM_LENGTH_PENALTY},
                        },
                    },
                    ensure_ascii=False,
                )
            )
            initialized = True
        elif event_type == "session.created" and initialized:
            await _send_json(
                client,
                {"type": "session.created", "provider": "minicpm", "video": video},
            )
            return
        elif event_type == "error":
            error = event.get("error") or {}
            raise RuntimeError(error.get("message") or "MiniCPM session initialization failed")


async def _bridge_minicpm(client, session_id: str, pack: dict, video: bool):
    upstream = await _connect(
        _minicpm_endpoint(video),
        _minicpm_headers(),
        use_proxy=MINICPM_USE_PROXY,
    )
    await _initialize_minicpm(upstream, client, pack, video)
    _log(
        f"已接通 MiniCPM-o · {MINICPM_MODEL} · mode={'video' if video else 'audio'} · "
        f"session={session_id}"
    )

    chunk_bytes = max(
        2,
        PROVIDER_INFO["minicpm"]["input_sample_rate"]
        * 2
        * MINICPM_INPUT_CHUNK_MS
        // 1000,
    )
    audio_buffer = bytearray()
    latest_frame: str | None = None
    response_id = ""
    upstream_response_id = ""
    response_open = False
    output_text: list[str] = []

    async def finish_response():
        nonlocal response_id, upstream_response_id, response_open, output_text
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
        upstream_response_id = ""
        response_open = False
        output_text = []

    async def ensure_response(candidate_id: str | None):
        nonlocal response_id, upstream_response_id, response_open, output_text
        candidate_id = candidate_id or ""
        if response_open and candidate_id and candidate_id != upstream_response_id:
            await finish_response()
        if response_open:
            return
        upstream_response_id = candidate_id
        response_id = candidate_id or f"minicpm-{uuid.uuid4().hex}"
        response_open = True
        output_text = []
        await _send_json(
            client,
            {"type": "response.created", "id": response_id, "response": {"id": response_id}},
        )

    async def pump_up():
        nonlocal latest_frame
        while True:
            raw = await client.receive_text()
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            event_type = event.get("type")
            if event_type == "ling.video_frame" and video:
                frame = _minicpm_video_frame(event)
                if frame:
                    latest_frame = frame
                continue
            if event_type != "input_audio_buffer.append" or not event.get("audio"):
                continue
            try:
                audio_buffer.extend(_decode_base64(event["audio"], 2))
            except ValueError:
                continue
            while len(audio_buffer) >= chunk_bytes:
                chunk = bytes(audio_buffer[:chunk_bytes])
                del audio_buffer[:chunk_bytes]
                frame = latest_frame
                latest_frame = None
                await upstream.send(
                    json.dumps(_minicpm_input_message(chunk, video, frame))
                )

    async def pump_down():
        async for raw in upstream:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            event_type = event.get("type")
            if event_type == "response.output.delta":
                kind = event.get("kind")
                if kind == "listen":
                    await finish_response()
                elif kind == "text" and isinstance(event.get("text"), str):
                    await ensure_response(event.get("response_id"))
                    delta = event["text"]
                    output_text.append(delta)
                    await _send_json(
                        client,
                        {
                            "type": "response.audio_transcript.delta",
                            "response_id": response_id,
                            "delta": delta,
                        },
                    )
                elif kind == "audio" and event.get("audio"):
                    try:
                        audio = _float32_b64_to_pcm16_b64(event["audio"])
                    except ValueError:
                        continue
                    await ensure_response(event.get("response_id"))
                    await _send_json(
                        client, {"type": "response.audio.delta", "delta": audio}
                    )
            elif event_type == "error":
                error = event.get("error") or {}
                _log(f"MiniCPM error：{error.get('code')} {error.get('message')}")
                await _send_json(client, {"type": "error", **error})
            elif event_type == "session.closed":
                await finish_response()
                return

    await _run_pumps(
        client,
        upstream,
        pump_up,
        pump_down,
        close_message={"type": "session.close", "reason": "user_stop"},
    )


async def _run_pumps(client, upstream, pump_up, pump_down, close_message=None):
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
        if close_message:
            try:
                await upstream.send(json.dumps(close_message))
            except Exception:
                pass
        try:
            await upstream.close()
        except Exception:
            pass
        try:
            await client.close()
        except Exception:
            pass


async def bridge(
    client, session_id: str, provider: str | None = None, video: bool = False
):
    """浏览器与指定实时模型之间的双向代理，并把转写写入记忆引擎。"""
    await client.accept()
    provider = (provider or default_provider()).lower()
    if provider not in PROVIDER_INFO:
        await _send_json(client, {"type": "ling.error", "message": "不支持的实时模型"})
        await client.close()
        return
    if not provider_available(provider):
        env_name = {
            "gemini": "GEMINI_API_KEY",
            "stepfun": "STEPFUN_API_KEY",
            "volcengine": "VOLCENGINE_RTC_APP_ID / APP_KEY / ACCESS_KEY / SECRET_KEY",
            "minicpm": "LING_MINICPM_BASE_URL 或 LING_MINICPM_REALTIME_URL",
        }[provider]
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
        if provider == "volcengine":
            raise RuntimeError("Volcengine uses the ByteRTC REST control plane")
        if provider == "gemini":
            await _bridge_gemini(client, session_id, session["pack"])
        elif provider == "minicpm":
            await _bridge_minicpm(client, session_id, session["pack"], video)
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
