"""StepFun 实时语音接入（stepaudio-2.5-realtime，全双工语音对话）。

浏览器 ──WS──> 本服务 /api/realtime/ws ──WSS──> api.stepfun.com/v1/realtime

为什么要过一层后端代理：
1. 浏览器 WebSocket 发不了 Authorization header，API key 也不能下发到前端；
2. instructions（人设 + 记忆包）由后端拼装注入，前端无权改写；
3. 上行/下行转写在这里截获，喂给 engine 的编织追踪器 —— 语音对话和文字对话
   共享同一套曝光/识别/产出、分享事件、撤退规则的记账逻辑。

协议即 OpenAI Realtime 风格事件流；音频 pcm16 / 24kHz / 单声道 / base64
（采样率来自官方 Step-Realtime-Console：sampleRate = 24000）。

环境变量：
    STEPFUN_API_KEY           必填，没有它整个模块不可用
    LING_STEPFUN_MODEL        默认 stepaudio-2.5-realtime
    LING_STEPFUN_VOICE        默认 linjiajiejie（官方音色，也可填克隆音色 ID）
    LING_STEPFUN_URL          默认 wss://api.stepfun.com/v1/realtime
    LING_STEPFUN_SILENCE_MS   VAD 判定说完话的静音时长，默认 600（孩子说话多停顿）
"""
import asyncio
import json
import os
import sys

from . import engine, prompts

WS_URL = os.environ.get("LING_STEPFUN_URL", "wss://api.stepfun.com/v1/realtime")
MODEL = os.environ.get("LING_STEPFUN_MODEL", "stepaudio-2.5-realtime")
VOICE = os.environ.get("LING_STEPFUN_VOICE", "linjiajiejie")
SILENCE_MS = int(os.environ.get("LING_STEPFUN_SILENCE_MS", "600"))
SAMPLE_RATE = 24000  # 上下行一致，pcm16 单声道

# 浏览器允许直发上游的事件（其余一律丢弃；session.update 只能由后端发）
CLIENT_EVENTS = {
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


def available() -> bool:
    return bool(os.environ.get("STEPFUN_API_KEY"))


def info() -> dict:
    return {"available": available(), "model": MODEL, "voice": VOICE,
            "sample_rate": SAMPLE_RATE}


def _log(msg: str):
    print(f"[realtime] {msg}", file=sys.stderr, flush=True)


async def _connect_upstream():
    import websockets
    headers = {"Authorization": f"Bearer {os.environ['STEPFUN_API_KEY']}"}
    url = f"{WS_URL}?model={MODEL}"
    try:  # websockets >= 14 改名 additional_headers
        return await websockets.connect(url, additional_headers=headers, max_size=None)
    except TypeError:
        return await websockets.connect(url, extra_headers=headers, max_size=None)


def _session_update(pack: dict) -> str:
    return json.dumps({
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": prompts.build_doll_system(pack) + VOICE_NOTE,
            "voice": VOICE,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "turn_detection": {
                "type": "server_vad",
                "prefix_padding_ms": 500,
                "silence_duration_ms": SILENCE_MS,
            },
        },
    }, ensure_ascii=False)


async def _send_json(client, obj: dict):
    await client.send_text(json.dumps(obj, ensure_ascii=False))


async def bridge(client, session_id: str):
    """浏览器 WS ↔ StepFun WSS 双向泵，顺带把转写喂进编织追踪器。"""
    await client.accept()
    if not available():
        await _send_json(client, {"type": "ling.error",
                                  "message": "没设 STEPFUN_API_KEY，实时语音不可用"})
        await client.close()
        return
    if not engine.get_session(session_id):
        await _send_json(client, {"type": "ling.error",
                                  "message": "会话不存在，请先开始会话"})
        await client.close()
        return

    try:
        upstream = await _connect_upstream()
    except Exception as e:
        _log(f"连接 StepFun 失败：{type(e).__name__}: {e}")
        await _send_json(client, {"type": "ling.error",
                                  "message": f"连不上 StepFun：{e}"})
        await client.close()
        return

    pack = engine.get_session(session_id)["pack"]
    await upstream.send(_session_update(pack))
    # 主动让玩偶先开口打招呼：不依赖上游是否回 session.updated（StepFun 实测不一定回），
    # 注入人设后直接触发一次 response，孩子一接通就被亲切地喊一声。
    await upstream.send(json.dumps({"type": "response.create"}, ensure_ascii=False))
    _log(f"已接通 {MODEL} · voice={VOICE} · session={session_id}（已触发开场问候）")

    # 每个 response 的转写增量缓存：response.cancel 打断时 audio_transcript.done
    # 不一定来，孩子却已经听到半句 —— 用攒下的增量兜底记账
    partial: dict[str, list] = {}
    recorded: set[str] = set()

    async def push_state(state: dict | None):
        if state:
            await _send_json(client, {"type": "ling.state", **state})

    def record_doll(rid: str, text: str):
        if not rid or rid in recorded:
            return None
        recorded.add(rid)
        partial.pop(rid, None)
        return engine.record_voice_doll(session_id, text)

    async def pump_up():
        while True:
            raw = await client.receive_text()
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if ev.get("type") not in CLIENT_EVENTS:
                continue
            if ev.get("type") == "conversation.item.create":
                # 通话中打字发来的文字，同样走编织追踪
                for part in (ev.get("item") or {}).get("content") or []:
                    if part.get("type") in ("input_text", "text") and part.get("text"):
                        engine.record_voice_user(session_id, part["text"])
            await upstream.send(raw)

    async def pump_down():
        async for raw in upstream:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            t = ev.get("type")
            if t == "conversation.item.input_audio_transcription.completed":
                engine.record_voice_user(session_id, ev.get("transcript") or "")
            elif t == "response.audio_transcript.delta":
                partial.setdefault(ev.get("response_id") or "", []).append(ev.get("delta") or "")
            elif t == "response.audio_transcript.done":
                state = record_doll(ev.get("response_id") or "", ev.get("transcript") or "")
                await client.send_text(raw)
                await push_state(state)
                continue
            elif t == "response.done":
                resp = ev.get("response") or {}
                rid = resp.get("id") or ""
                if rid and rid not in recorded:
                    # 被打断/纯文本 response 的兜底：先攒的增量，再翻 output
                    text = "".join(partial.get(rid) or [])
                    if not text:
                        text = " ".join(
                            p.get("transcript") or p.get("text") or ""
                            for item in resp.get("output") or []
                            for p in item.get("content") or []).strip()
                    state = record_doll(rid, text)
                    await client.send_text(raw)
                    await push_state(state)
                    continue
            elif t == "error":
                _log(f"上游 error：{ev.get('code')} {ev.get('message')}")
            await client.send_text(raw)

    up = asyncio.create_task(pump_up())
    down = asyncio.create_task(pump_down())
    try:
        await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
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
        _log(f"通话结束 · session={session_id}")
