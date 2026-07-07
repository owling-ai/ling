"""LLM 接入层：有 ANTHROPIC_API_KEY 就走真模型，没有就回退到规则引擎（纯软件兜底）。

- 对话（热路径）：LING_CHAT_MODEL，默认 claude-opus-4-8
- 冷路径工人（抽取/反思/生活时钟，异步不在乎延迟）：LING_WORKER_MODEL，默认 claude-haiku-4-5
- 所有真模型调用失败都静默降级到 mock，demo 永远不会挂。
"""
import json
import os
import re

CHAT_MODEL = os.environ.get("LING_CHAT_MODEL", "claude-opus-4-8")
WORKER_MODEL = os.environ.get("LING_WORKER_MODEL", "claude-haiku-4-5")

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        _client = anthropic.Anthropic()
    except Exception:
        _client = None
    return _client


def live_mode() -> bool:
    return _get_client() is not None


def mode_info() -> dict:
    live = live_mode()
    return {
        "mode": "live" if live else "mock",
        "chat_model": CHAT_MODEL if live else "规则引擎（无 API key 兜底）",
        "worker_model": WORKER_MODEL if live else "规则引擎（无 API key 兜底）",
    }


def chat(system: str, messages: list, max_tokens: int = 1024) -> str | None:
    """热路径对话。返回 None 表示需要 mock 兜底。"""
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model=CHAT_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception:
        return None


def worker_json(prompt: str, max_tokens: int = 2048):
    """冷路径工人：让 LLM 输出 JSON 并解析。返回 None 表示需要 mock 兜底。"""
    client = _get_client()
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model=WORKER_MODEL,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        m = re.search(r"\[.*\]|\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None
