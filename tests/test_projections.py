from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from backend import db, experience, media, seed


PARENT_FORBIDDEN = {
    "transcript",
    "transcripts",
    "quote",
    "quotes",
    "session_id",
    "prompt",
    "system_prompt",
    "provider",
    "provider_response",
    "job",
    "job_id",
    "successes",
    "exposures",
    "due_date",
    "next_review_at",
    "private_canon",
    "delete_url",
    "deletion_target",
    "fact_id",
    "diary_id",
    "raw",
    "raw_text",
}
CHILD_FORBIDDEN = PARENT_FORBIDDEN | {
    "mastery",
    "mood",
    "attention",
    "growth_moments",
    "red_lines",
}


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for nested in value.values() for key in _keys(nested)}
    if isinstance(value, list):
        return {key for nested in value for key in _keys(nested)}
    return set()


@pytest.fixture
def projection_service(isolated_db: Path):
    seed.seed()
    conn = db.get_conn()
    for table in ("pocket_entries", "keepsakes", "generation_jobs", "moments"):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()
    clock = [datetime(2026, 7, 11, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))]
    service = experience.ExperienceService(
        catalog=media.default_catalog(reload=True),
        now_fn=lambda: clock[0],
        timezone="Asia/Shanghai",
        generation_delay_seconds=3,
    )
    published = service.settle_candidate(
        1, "session", "published", "canon_choice", {"choice": "橡果味"}
    )
    clock[0] += timedelta(seconds=4)
    service.refresh_moment(published["moment_id"])
    pending = service.settle_candidate(
        1, "session", "pending", "word_taught", {"word": "kite"}
    )
    return service, clock, published, pending


def test_child_world_is_display_ready_and_contains_no_private_projection(
    projection_service,
) -> None:
    service, clock, _, _ = projection_service
    world = service.child_world_now(1, now=clock[0])
    assert set(world) == {
        "mode",
        "timezone",
        "next_transition_at",
        "doll",
        "event",
        "sleep_message",
        "memory_summary",
    }
    assert world["mode"] == "day"
    assert world["doll"]["name"] == "灵灵"
    assert world["event"]["event_id"] == "hill-wind"
    assert world["event"]["media"]["src"].startswith("/demo-media/")
    assert not (_keys(world) & CHILD_FORBIDDEN)


def test_child_feed_merges_public_and_published_personal_but_separates_pending(
    projection_service,
) -> None:
    service, clock, published, pending = projection_service
    feed = service.child_feed(1, now=clock[0])
    kinds = {item["kind"] for item in feed["items"]}
    assert kinds == {"public", "personal"}
    assert any(item["id"] == published["moment_id"] for item in feed["items"])
    assert [item["id"] for item in feed["pending"]] == [pending["moment_id"]]
    assert not (_keys(feed) & CHILD_FORBIDDEN)


def test_parent_today_is_aggregated_and_non_diagnostic(projection_service) -> None:
    service, clock, _, _ = projection_service
    today = service.parent_today(1, now=clock[0])
    assert set(today) == {
        "date",
        "child_display_name",
        "doll_display_name",
        "metrics",
        "mood",
        "attention",
        "tonight",
    }
    assert set(today["metrics"]) == {
        "minutes_together",
        "topics_count",
        "new_words_spoken",
    }
    assert today["mood"]["disclaimer"] == "大致参考，非诊断"
    assert not (_keys(today) & PARENT_FORBIDDEN)


def test_parent_growth_maps_srs_to_three_display_levels(projection_service) -> None:
    service, clock, _, _ = projection_service
    growth = service.parent_growth(1, period="week", now=clock[0])
    assert set(growth) == {
        "period_label",
        "metrics",
        "words",
        "next_review",
        "retreat",
        "growth_moments",
    }
    assert {word["level"] for word in growth["words"]} <= {
        "exposed",
        "recognized",
        "produced",
    }
    assert all(set(word) <= {"text", "meaning", "level"} for word in growth["words"])
    assert growth["growth_moments"] == [
        {
            "before": "有点怕黑，睡觉要开灯",
            "after": "已经不怕黑了，因为有了恐龙小夜灯",
        }
    ]
    assert not (_keys(growth) & PARENT_FORBIDDEN)


def test_parent_memory_uses_projection_ids_and_has_no_deletion_targets(
    projection_service,
) -> None:
    service, clock, _, _ = projection_service
    memory = service.parent_memory(1, limit=20, now=clock[0])
    assert set(memory) == {"items", "next_cursor", "boundary_summary", "rights"}
    assert all(str(item["id"]).startswith(("moment:", "attention:", "growth:")) for item in memory["items"])
    assert {item["kind"] for item in memory["items"]} <= {
        "moment",
        "attention",
        "growth",
    }
    assert memory["rights"] == {
        "export_available": False,
        "deletion_request_available": False,
        "status_note": "黑客松版本仅展示数据权利说明，不执行导出或注销。",
    }
    assert not (_keys(memory) & PARENT_FORBIDDEN)


def test_parent_guardian_is_read_only_and_ai_identity_is_fixed(
    projection_service,
) -> None:
    service, clock, _, _ = projection_service
    guardian = service.parent_guardian(1, now=clock[0])
    assert set(guardian) == {
        "availability_windows",
        "daily_limit_minutes",
        "used_today_minutes",
        "bedtime",
        "device",
        "red_lines",
        "ai_identity",
        "notifications",
    }
    assert guardian["ai_identity"]["fixed"] is True
    assert guardian["daily_limit_minutes"] == 40
    assert not (_keys(guardian) & PARENT_FORBIDDEN)
