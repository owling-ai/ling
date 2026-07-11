"""Server-side Gemini text generation for the legacy child-voice gateway."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


GEMINI_TEXT_URL = os.environ.get(
    "LING_GEMINI_OPENAI_URL",
    "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
).strip()
GEMINI_TEXT_MODEL = os.environ.get(
    "LING_GEMINI_PCM_MODEL",
    os.environ.get("LING_VOLC_GEMINI_MODEL", "gemini-3.1-flash-lite"),
).strip()
GEMINI_TEXT_TIMEOUT_SECONDS = max(
    5, int(os.environ.get("LING_GEMINI_PCM_TIMEOUT_SECONDS", "30"))
)
GEMINI_TEXT_MAX_HISTORY = max(
    4, int(os.environ.get("LING_GEMINI_PCM_MAX_HISTORY", "30"))
)


def available() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY", "").strip())


def _messages(
    system_instruction: str,
    history: list[dict],
    prompt: str | None,
) -> list[dict]:
    messages = [{"role": "system", "content": system_instruction}]
    for item in history[-GEMINI_TEXT_MAX_HISTORY:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    normalized_prompt = str(prompt or "").strip()
    if normalized_prompt:
        messages.append({"role": "user", "content": normalized_prompt})
    return messages


def generate_reply(
    system_instruction: str,
    history: list[dict],
    *,
    prompt: str | None = None,
) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Gemini API key is not configured")
    body = json.dumps(
        {
            "model": GEMINI_TEXT_MODEL,
            "messages": _messages(system_instruction, history, prompt),
            "temperature": 0.7,
            "max_tokens": 512,
            "stream": False,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        GEMINI_TEXT_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    for attempt in range(2):
        try:
            with urllib.request.urlopen(
                request, timeout=GEMINI_TEXT_TIMEOUT_SECONDS
            ) as response:
                payload = json.load(response)
            break
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if attempt or exc.code not in {429, 500, 502, 503, 504}:
                raise RuntimeError(
                    f"Gemini text HTTP {exc.code}: {detail[:300]}"
                ) from exc
            exc.close()
        except urllib.error.URLError as exc:
            if attempt:
                raise RuntimeError(f"Gemini text network error: {exc.reason}") from exc
        time.sleep(0.15)
    else:
        raise RuntimeError("Gemini text is unavailable")

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Gemini text returned an invalid response") from exc
    if isinstance(content, list):
        content = "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict)
        )
    text = str(content or "").strip()
    if not text:
        raise RuntimeError("Gemini text returned an empty response")
    return text
