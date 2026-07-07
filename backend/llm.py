"""LLM 接入层：三个 provider，自动选择，任何失败都静默降级，demo 永远不会挂。

优先级（可用 LING_PROVIDER=openai|anthropic|mock 强制指定）：
1. openai    —— 任何 OpenAI 兼容端点，设 LING_OPENAI_BASE_URL 即启用：
                · 本地 MiniCPM-o 4.5（vLLM-omni）：
                    vllm serve openbmb/MiniCPM-o-4_5 --trust-remote-code --port 8001
                    export LING_OPENAI_BASE_URL=http://localhost:8001/v1
                · OpenRouter 等第三方：
                    export LING_OPENAI_BASE_URL=https://openrouter.ai/api/v1
                    export LING_OPENAI_API_KEY=sk-or-...
                    export LING_OPENAI_MODEL=deepseek/deepseek-chat
                全模态模型（MiniCPM-o 这类）自动开启摄像头画面输入，
                纯文本模型（DeepSeek 这类）自动关闭；LING_OPENAI_VISION=1/0 可强制。
2. anthropic —— 设了 ANTHROPIC_API_KEY 就可用。
                对话 LING_CHAT_MODEL（默认 claude-opus-4-8），
                冷路径 LING_WORKER_MODEL（默认 claude-haiku-4-5，异步不在乎延迟）。
3. mock      —— 规则引擎（纯软件兜底，零依赖零网络）。

真·全双工（连续音视频流、边听边说）走 OpenBMB 官方 MiniCPM-o-Demo 的
WebSocket 网关，是硬件阶段的升级路线，见 README「全双工路线」一节。
"""
import json
import os
import re
import urllib.request

CHAT_MODEL = os.environ.get("LING_CHAT_MODEL", "claude-opus-4-8")
WORKER_MODEL = os.environ.get("LING_WORKER_MODEL", "claude-haiku-4-5")

OPENAI_BASE_URL = os.environ.get("LING_OPENAI_BASE_URL", "").rstrip("/")
OPENAI_API_KEY = os.environ.get("LING_OPENAI_API_KEY", "EMPTY")
OPENAI_MODEL = os.environ.get("LING_OPENAI_MODEL", "openbmb/MiniCPM-o-4_5")

_anthropic_client = None


def _get_anthropic():
    global _anthropic_client
    if _anthropic_client is not None:
        return _anthropic_client
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        _anthropic_client = anthropic.Anthropic()
    except Exception:
        _anthropic_client = None
    return _anthropic_client


def provider() -> str:
    forced = os.environ.get("LING_PROVIDER", "").lower()
    if forced in ("openai", "minicpm", "openrouter") and OPENAI_BASE_URL:
        return "openai"
    if forced == "anthropic" and _get_anthropic():
        return "anthropic"
    if forced == "mock":
        return "mock"
    if OPENAI_BASE_URL:
        return "openai"
    if _get_anthropic():
        return "anthropic"
    return "mock"


def live_mode() -> bool:
    return provider() != "mock"


# 模型名里出现这些词就认为端点能吃图像/视频帧
_VISION_HINTS = ("minicpm-o", "minicpm-v", "omni", "-vl", "vl-", "vision", "gpt-4o", "gemini")


def supports_vision() -> bool:
    """摄像头画面只有全模态/多模态端点吃得下（DeepSeek 这类纯文本模型自动关闭）。"""
    if provider() != "openai":
        return False
    forced = os.environ.get("LING_OPENAI_VISION", "")
    if forced in ("1", "true", "yes"):
        return True
    if forced in ("0", "false", "no"):
        return False
    return any(h in OPENAI_MODEL.lower() for h in _VISION_HINTS)


def mode_info() -> dict:
    p = provider()
    return {
        "mode": "live" if p != "mock" else "mock",
        "provider": p,
        "chat_model": {"openai": OPENAI_MODEL, "anthropic": CHAT_MODEL,
                       "mock": "规则引擎（无 API key 兜底）"}[p],
        "worker_model": {"openai": OPENAI_MODEL, "anthropic": WORKER_MODEL,
                         "mock": "规则引擎（无 API key 兜底）"}[p],
        "vision": supports_vision(),
    }


# ---------------------------------------------------------------- OpenAI 兼容端点（MiniCPM-o）

def _openai_chat(messages: list, max_tokens: int) -> str | None:
    """POST {base}/chat/completions。用标准库，不给离线 demo 增加依赖。"""
    try:
        req = urllib.request.Request(
            f"{OPENAI_BASE_URL}/chat/completions",
            data=json.dumps({
                "model": OPENAI_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": 0.7,
            }).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {OPENAI_API_KEY}"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return None


def _with_image(messages: list, image_b64: str | None) -> list:
    """把 base64 JPEG 帧塞进最后一条用户消息（OpenAI content parts 格式，
    vLLM-omni 服务的 MiniCPM-o 4.5 按此格式吃图像/视频帧）。"""
    if not image_b64:
        return messages
    out = [dict(m) for m in messages]
    for m in reversed(out):
        if m["role"] == "user":
            m["content"] = [
                {"type": "text", "text": m["content"]},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ]
            break
    return out


# ---------------------------------------------------------------- 统一入口

def chat(system: str, messages: list, max_tokens: int = 1024,
         image_b64: str | None = None) -> str | None:
    """热路径对话。返回 None 表示需要 mock 兜底。"""
    p = provider()
    if p == "openai":
        return _openai_chat(
            [{"role": "system", "content": system}] + _with_image(messages, image_b64),
            max_tokens)
    if p == "anthropic":
        client = _get_anthropic()
        try:
            resp = client.messages.create(
                model=CHAT_MODEL, max_tokens=max_tokens,
                system=system, messages=messages)
            return "".join(b.text for b in resp.content if b.type == "text").strip()
        except Exception:
            return None
    return None


def worker_json(prompt: str, max_tokens: int = 2048):
    """冷路径工人：让模型输出 JSON 并解析。返回 None 表示需要 mock 兜底。"""
    p = provider()
    text = None
    if p == "openai":
        text = _openai_chat([{"role": "user", "content": prompt}], max_tokens)
    elif p == "anthropic":
        client = _get_anthropic()
        try:
            resp = client.messages.create(
                model=WORKER_MODEL, max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}])
            text = "".join(b.text for b in resp.content if b.type == "text")
        except Exception:
            text = None
    if not text:
        return None
    try:
        m = re.search(r"\[.*\]|\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else None
    except (ValueError, AttributeError):
        return None
