"""LLM 接入层：只服务冷路径记忆工人（日记/事实/反思/生活时钟/记忆钩子）。

实时对话由 Gemini Live 或 StepFun Realtime 承担（见 realtime.py），不经过这里。

冷路径端点（异步任务，不在乎延迟）：
    LING_WORKER_BASE_URL / LING_WORKER_API_KEY / LING_WORKER_MODEL
    · 任何 OpenAI 兼容端点（SiliconFlow / OpenRouter / DeepSeek 官方 / 本地 ollama ...）
    · 没设时回落到 LING_OPENAI_*（旧配置照跑）

优先级（LING_PROVIDER=openai|anthropic|mock 可强制）：
1. openai    —— 配了 OpenAI 兼容端点。
2. anthropic —— 设了 ANTHROPIC_API_KEY，模型用 LING_ANTHROPIC_WORKER_MODEL。
3. mock      —— 规则抽取器（纯软件兜底，零依赖零网络，输出结构与 LLM 版一致）。
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request


def _env(*names, default=""):
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


WORKER_EP = {
    "base": _env("LING_WORKER_BASE_URL", "LING_OPENAI_BASE_URL").rstrip("/"),
    "key": _env("LING_WORKER_API_KEY", "LING_OPENAI_API_KEY", default="EMPTY"),
    "model": _env("LING_WORKER_MODEL", "LING_OPENAI_MODEL", default="deepseek-chat"),
}

ANTHROPIC_WORKER_MODEL = os.environ.get("LING_ANTHROPIC_WORKER_MODEL", "claude-haiku-4-5")
_EMPTY_KEYS = {"", "EMPTY", "NONE", "NULL", "TODO", "CHANGEME", "PLACEHOLDER"}
_TRUTHY = {"1", "true", "yes", "on"}

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


def _worker_ep() -> dict:
    """Read worker settings lazily so tests and local shells can override imports."""
    return {
        "base": _env(
            "LING_WORKER_BASE_URL",
            "LING_OPENAI_BASE_URL",
            default=WORKER_EP.get("base", ""),
        ).rstrip("/"),
        "key": _env(
            "LING_WORKER_API_KEY",
            "LING_OPENAI_API_KEY",
            default=WORKER_EP.get("key", "EMPTY"),
        ),
        "model": _env(
            "LING_WORKER_MODEL",
            "LING_OPENAI_MODEL",
            default=WORKER_EP.get("model", "deepseek-chat"),
        ),
    }


def _has_real_key(value: str) -> bool:
    return value.strip().upper() not in _EMPTY_KEYS


def _allow_empty_openai_key() -> bool:
    return os.environ.get("LING_WORKER_ALLOW_EMPTY_KEY", "").lower() in _TRUTHY


def _openai_ready(ep: dict) -> bool:
    return bool(ep["base"]) and (_has_real_key(ep["key"]) or _allow_empty_openai_key())


def _worker_timeout_seconds() -> float:
    raw = os.environ.get("LING_WORKER_TIMEOUT_SECONDS", "10")
    try:
        timeout = float(raw)
    except ValueError:
        timeout = 10.0
    return max(1.0, min(timeout, 120.0))


def provider() -> str:
    forced = os.environ.get("LING_PROVIDER", "").lower()
    ep = _worker_ep()
    if forced == "mock":
        return "mock"
    if forced == "openai":
        return "openai" if _openai_ready(ep) else "mock"
    if forced == "anthropic":
        return "anthropic" if _get_anthropic() else "mock"
    if _openai_ready(ep):
        return "openai"
    if _get_anthropic():
        return "anthropic"
    return "mock"


def worker_live() -> bool:
    return provider() != "mock"


def mode_info() -> dict:
    p = provider()
    ep = _worker_ep()
    model = {"openai": WORKER_EP["model"], "anthropic": ANTHROPIC_WORKER_MODEL,
             "mock": "规则抽取器（无 API key 兜底）"}[p]
    if p == "openai":
        model = ep["model"]
    return {"worker_provider": p, "worker_model": model, "worker_base": ep["base"]}


# ---------------------------------------------------------------- OpenAI 兼容端点

def _log_fail(ep: dict, e: Exception):
    if isinstance(e, urllib.error.HTTPError):
        detail = f"返回 {e.code}：{e.read()[:300].decode(errors='replace')}"
    else:
        detail = f"请求失败（{type(e).__name__}: {e}）"
    print(f"[llm] {ep['base']} · {ep['model']} {detail} —— 本轮降级到规则抽取器",
          file=sys.stderr, flush=True)


def _openai_chat(ep: dict, messages: list, max_tokens: int) -> str | None:
    """POST {base}/chat/completions。用标准库，不给离线 demo 增加依赖。"""
    req = urllib.request.Request(
        f"{ep['base']}/chat/completions",
        data=json.dumps({"model": ep["model"], "messages": messages,
                         "max_tokens": max_tokens, "temperature": 0.7}).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {ep['key']}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_worker_timeout_seconds()) as resp:
            data = json.loads(resp.read())
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception as e:
        _log_fail(ep, e)
        return None


# ---------------------------------------------------------------- 统一入口

def worker_json(prompt: str, max_tokens: int = 2048):
    """冷路径工人：让模型输出 JSON 并解析。返回 None 表示需要 mock 兜底。"""
    p = provider()
    text = None
    if p == "openai":
        text = _openai_chat(_worker_ep(), [{"role": "user", "content": prompt}], max_tokens)
    elif p == "anthropic":
        client = _get_anthropic()
        try:
            resp = client.messages.create(
                model=ANTHROPIC_WORKER_MODEL, max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}])
            text = "".join(b.text for b in resp.content if b.type == "text")
        except Exception as e:
            print(f"[llm] anthropic 请求失败（{e}）—— 本轮降级到规则抽取器",
                  file=sys.stderr, flush=True)
            text = None
    if not text:
        return None
    try:
        m = re.search(r"\[.*\]|\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else None
    except (ValueError, AttributeError):
        return None
