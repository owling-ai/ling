"""Allowlisted child-voice profiles used by the realtime RTC pipeline."""

from __future__ import annotations

import os


NATURAL_CHILD_STYLE = (
    "请用自然、放松、生活化的日常语气说话，减少表演感。不要夹嗓，"
    "不要使用夸张卡通腔，不要故意拖长尾音。像一个八九岁的小朋友"
    "跟熟悉的同伴正常聊天。"
)

VOICE_PROFILES = (
    {
        "id": "sunny",
        "name": "小晴天",
        "voice": "zh_male_tiancaitongsheng_uranus_bigtts",
        "resource_id": "seed-tts-2.0",
        "description": "清亮自然，灵动但不吵闹",
        "preview_url": "/assets/voices/sunny.wav",
        "style_instruction": NATURAL_CHILD_STYLE,
    },
    {
        "id": "sprout",
        "name": "小青芽",
        "voice": "ICL_uranus_zh_female_jiaxiaozi_tob",
        "resource_id": "seed-tts-2.0",
        "description": "松弛亲切，活泼但不做作",
        "preview_url": "/assets/voices/sprout.wav",
        "style_instruction": NATURAL_CHILD_STYLE,
    },
)

_PROFILE_BY_ID = {profile["id"]: profile for profile in VOICE_PROFILES}
_configured_default = os.environ.get("LING_VOLC_VOICE_PROFILE", "sunny").strip().lower()
DEFAULT_VOICE_PROFILE = (
    _configured_default if _configured_default in _PROFILE_BY_ID else "sunny"
)


def resolve_voice_profile(profile_id: str | None = None) -> dict:
    requested = (profile_id or DEFAULT_VOICE_PROFILE).strip().lower()
    return _PROFILE_BY_ID.get(requested, _PROFILE_BY_ID["sunny"])


def public_voice_profiles() -> list[dict]:
    public_keys = ("id", "name", "description", "preview_url")
    return [
        {key: profile[key] for key in public_keys}
        for profile in VOICE_PROFILES
    ]
