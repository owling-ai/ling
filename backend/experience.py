"""Experience projections built from memory facts and deterministic demo media."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone as dt_timezone
from typing import Callable
from zoneinfo import ZoneInfo

from . import db, media


EVENT_VALUE_FIELDS = {
    "word_taught": "word",
    "canon_choice": "choice",
    "story_beat": "beat",
    "growth_change": "change",
}
MAX_DAILY_MOMENTS = 3
MAX_GENERATION_ATTEMPTS = 2


class ExperienceNotFound(KeyError):
    pass


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=dt_timezone.utc)


def _iso(value: datetime) -> str:
    return _aware(value).isoformat(timespec="seconds")


class ExperienceService:
    def __init__(
        self,
        catalog: media.MediaCatalog | None = None,
        *,
        now_fn: Callable[[], datetime] | None = None,
        timezone: str = "Asia/Shanghai",
        generation_delay_seconds: int = 3,
    ):
        self.catalog = catalog or media.default_catalog()
        self.now_fn = now_fn or (lambda: datetime.now(dt_timezone.utc))
        self.timezone = timezone
        self.zone = ZoneInfo(timezone)
        self.provider = media.MockMediaProvider(
            self.catalog,
            now_fn=self.now_fn,
            delay_seconds=generation_delay_seconds,
        )

    def now(self) -> datetime:
        return _aware(self.now_fn()).astimezone(self.zone)

    @staticmethod
    def _idempotency_key(
        child_id: int,
        source_type: str,
        source_id: str,
        event_key: str,
        semantic_version: int,
    ) -> str:
        raw = f"{child_id}:{source_type}:{source_id}:{event_key}:v{semantic_version}"
        return "moment:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _settlement_result(self, moment: dict, created: bool) -> dict:
        job = db.q1(
            "SELECT id,attempt,status FROM generation_jobs WHERE moment_id=? "
            "ORDER BY attempt DESC LIMIT 1",
            (moment["id"],),
        )
        return {
            "moment_id": moment["id"],
            "job_id": job["id"] if job else None,
            "status": moment["status"],
            "attempt": job["attempt"] if job else None,
            "created": created,
        }

    def settle_candidate(
        self,
        child_id: int,
        source_type: str,
        source_id: str,
        event_key: str,
        payload: dict,
    ) -> dict:
        if event_key not in EVENT_VALUE_FIELDS:
            return {"status": "skipped", "reason": "insignificant"}
        if payload.get("meaningful", True) is not True:
            return {"status": "skipped", "reason": "insignificant"}
        if payload.get("safe", True) is not True:
            return {"status": "skipped", "reason": "unsafe"}
        event_value = str(payload.get(EVENT_VALUE_FIELDS[event_key], "")).strip()
        if not event_value:
            return {"status": "skipped", "reason": "insignificant"}
        semantic_version = int(payload.get("semantic_version", 1))
        idempotency_key = self._idempotency_key(
            child_id, source_type, str(source_id), event_key, semantic_version
        )
        matches = self.catalog.matching_assets(
            event_key, event_value, semantic_version
        )
        if not matches:
            return {"status": "skipped", "reason": "no_matching_asset"}
        asset = self.catalog.select_asset(
            event_key,
            event_value,
            semantic_version,
            idempotency_key,
        )
        moment_copy = asset.get("moment")
        if not isinstance(moment_copy, dict):
            return {"status": "skipped", "reason": "no_matching_asset"}

        existing = db.q1(
            "SELECT * FROM moments WHERE idempotency_key=?", (idempotency_key,)
        )
        if existing:
            return self._settlement_result(existing, False)

        now = self.now()
        created_at = _iso(now)
        with db.transaction(immediate=True) as conn:
            existing_row = conn.execute(
                "SELECT * FROM moments WHERE idempotency_key=?", (idempotency_key,)
            ).fetchone()
            if existing_row:
                moment = dict(existing_row)
                created = False
            else:
                count = conn.execute(
                    "SELECT COUNT(*) AS n FROM moments WHERE child_id=? AND local_date=? "
                    "AND status IN ('rendering','published')",
                    (child_id, now.date().isoformat()),
                ).fetchone()["n"]
                if count >= MAX_DAILY_MOMENTS:
                    return {"status": "skipped", "reason": "daily_quota"}
                moment_id = conn.execute(
                    "INSERT INTO moments("
                    "child_id,source_type,source_id,event_key,event_value,semantic_version,"
                    "idempotency_key,local_date,title,story,status,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,'rendering',?)",
                    (
                        child_id,
                        source_type,
                        str(source_id),
                        event_key,
                        event_value,
                        semantic_version,
                        idempotency_key,
                        now.date().isoformat(),
                        moment_copy["title"],
                        moment_copy["story"],
                        created_at,
                    ),
                ).lastrowid
                self.provider.submit(
                    {
                        "moment_id": moment_id,
                        "attempt": 1,
                        "media_kind": "video",
                        "event_key": event_key,
                        "event_value": event_value,
                        "semantic_version": semantic_version,
                        "idempotency_key": f"{idempotency_key}:attempt:1",
                        "allowed_asset_groups": [asset["asset_group"]],
                    },
                    conn=conn,
                )
                moment = dict(
                    conn.execute("SELECT * FROM moments WHERE id=?", (moment_id,)).fetchone()
                )
                created = True
        return self._settlement_result(moment, created)

    def _latest_job(self, moment_id: int) -> dict | None:
        return db.q1(
            "SELECT * FROM generation_jobs WHERE moment_id=? ORDER BY attempt DESC LIMIT 1",
            (moment_id,),
        )

    def _start_retry(self, moment: dict, failed_job: dict) -> dict:
        next_attempt = failed_job["attempt"] + 1
        with db.transaction(immediate=True) as conn:
            latest = conn.execute(
                "SELECT * FROM generation_jobs WHERE moment_id=? ORDER BY attempt DESC LIMIT 1",
                (moment["id"],),
            ).fetchone()
            if latest["attempt"] >= next_attempt:
                return dict(latest)
            job_id = self.provider.submit(
                {
                    "moment_id": moment["id"],
                    "attempt": next_attempt,
                    "media_kind": "video",
                    "event_key": moment["event_key"],
                    "event_value": moment["event_value"],
                    "semantic_version": moment["semantic_version"],
                    "idempotency_key": f'{moment["idempotency_key"]}:attempt:{next_attempt}',
                    "allowed_asset_groups": [failed_job["asset_group"]],
                },
                conn=conn,
            )
            return dict(
                conn.execute("SELECT * FROM generation_jobs WHERE id=?", (job_id,)).fetchone()
            )

    def refresh_moment(self, moment_id: int) -> dict:
        moment = db.q1("SELECT * FROM moments WHERE id=?", (moment_id,))
        if not moment:
            raise ExperienceNotFound(f"moment not found: {moment_id}")
        if moment["status"] in {"published", "failed"}:
            return self.moment_detail(moment_id)
        job = self._latest_job(moment_id)
        if not job:
            raise ExperienceNotFound(f"generation job not found for moment: {moment_id}")
        status = self.provider.poll(job["id"])
        job = self._latest_job(moment_id)
        if status == "failed":
            if job["attempt"] < MAX_GENERATION_ATTEMPTS:
                retry = self._start_retry(moment, job)
                return {
                    "id": moment_id,
                    "kind": "personal",
                    "status": "rendering",
                    "attempt": retry["attempt"],
                    "poll_after_ms": 700,
                }
            db.execute(
                "UPDATE moments SET status='failed',error_code=? "
                "WHERE id=? AND status='rendering'",
                (job.get("error_code") or "generation_failed", moment_id),
            )
            return self.moment_detail(moment_id)
        if status != "succeeded":
            return {
                "id": moment_id,
                "kind": "personal",
                "status": "rendering",
                "attempt": job["attempt"],
                "poll_after_ms": 700,
            }

        asset = self.provider.result(job["id"])
        published_at = _iso(self.now())
        with db.transaction(immediate=True) as conn:
            current = dict(
                conn.execute("SELECT * FROM moments WHERE id=?", (moment_id,)).fetchone()
            )
            if current["status"] == "rendering" and not current["published_asset_id"]:
                conn.execute(
                    "UPDATE moments SET status='published',published_asset_id=?,published_at=?,"
                    "error_code='' WHERE id=? AND status='rendering' AND published_asset_id IS NULL",
                    (asset["asset_id"], published_at, moment_id),
                )
                keepsake = (asset.get("moment") or {}).get("keepsake")
                if isinstance(keepsake, dict):
                    conn.execute(
                        "INSERT OR IGNORE INTO keepsakes("
                        "child_id,moment_id,name,description,appearance,image_url,created_at) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (
                            current["child_id"],
                            moment_id,
                            keepsake["name"],
                            keepsake["description"],
                            keepsake["appearance"],
                            keepsake.get("image_url"),
                            published_at,
                        ),
                    )
        return self.moment_detail(moment_id)

    def _keepsake_for_moment(self, moment_id: int) -> dict | None:
        row = db.q1(
            "SELECT k.*,COALESCE(p.collected,0) AS collected,p.collected_at "
            "FROM keepsakes k LEFT JOIN pocket_entries p "
            "ON p.child_id=k.child_id AND p.keepsake_id=k.id WHERE k.moment_id=?",
            (moment_id,),
        )
        if not row:
            return None
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "appearance": row["appearance"],
            "image_url": row["image_url"],
            "collected": bool(row["collected"]),
        }

    def moment_detail(self, moment_id: int) -> dict:
        moment = db.q1("SELECT * FROM moments WHERE id=?", (moment_id,))
        if not moment:
            raise ExperienceNotFound(f"moment not found: {moment_id}")
        detail = {
            "id": moment["id"],
            "kind": "personal",
            "status": moment["status"],
            "title": moment["title"],
        }
        if moment["status"] == "rendering":
            job = self._latest_job(moment_id)
            detail.update(
                {
                    "attempt": job["attempt"] if job else None,
                    "poll_after_ms": 700,
                }
            )
        elif moment["status"] == "failed":
            detail["error"] = {
                "code": moment.get("error_code") or "generation_failed",
                "message": "这个瞬间暂时没有生成成功",
            }
        else:
            asset = self.catalog.asset(moment["published_asset_id"])
            detail.update(
                {
                    "story": moment["story"],
                    "occurred_at": moment["published_at"] or moment["created_at"],
                    "media": self.catalog.public_asset(asset),
                    "keepsake": self._keepsake_for_moment(moment_id),
                }
            )
        return detail

    def personal_feed(self, child_id: int) -> dict:
        published = db.q(
            "SELECT id FROM moments WHERE child_id=? AND status='published' "
            "ORDER BY published_at DESC,id DESC",
            (child_id,),
        )
        pending = db.q(
            "SELECT id,title,created_at FROM moments WHERE child_id=? AND status='rendering' "
            "ORDER BY created_at DESC,id DESC",
            (child_id,),
        )
        return {
            "items": [self.moment_detail(row["id"]) for row in published],
            "pending": [
                {
                    "id": row["id"],
                    "kind": "personal",
                    "status": "rendering",
                    "title": row["title"],
                    "poll_after_ms": 700,
                }
                for row in pending
            ],
        }

    def pocket(self, child_id: int) -> dict:
        rows = db.q(
            "SELECT k.*,p.collected_at,m.id AS source_moment_id "
            "FROM pocket_entries p JOIN keepsakes k ON k.id=p.keepsake_id "
            "JOIN moments m ON m.id=k.moment_id "
            "WHERE p.child_id=? AND p.collected=1 AND m.status='published' "
            "ORDER BY p.collected_at DESC,k.id DESC",
            (child_id,),
        )
        return {
            "items": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "appearance": row["appearance"],
                    "image_url": row["image_url"],
                    "source_moment_id": row["source_moment_id"],
                    "collected_at": row["collected_at"],
                }
                for row in rows
            ]
        }

    def set_pocket(self, child_id: int, keepsake_id: int, collected: bool) -> dict:
        keepsake = db.q1(
            "SELECT k.id FROM keepsakes k JOIN moments m ON m.id=k.moment_id "
            "WHERE k.id=? AND k.child_id=? AND m.status='published'",
            (keepsake_id, child_id),
        )
        if not keepsake:
            raise ExperienceNotFound(f"keepsake not found: {keepsake_id}")
        now = _iso(self.now())
        collected_at = now if collected else None
        db.execute(
            "INSERT INTO pocket_entries(child_id,keepsake_id,collected,collected_at,updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(child_id,keepsake_id) DO UPDATE SET "
            "collected=excluded.collected,collected_at=excluded.collected_at,"
            "updated_at=excluded.updated_at",
            (child_id, keepsake_id, 1 if collected else 0, collected_at, now),
        )
        return {
            "keepsake_id": keepsake_id,
            "collected": collected,
            "updated_at": now,
        }

    def settle_session(self, session: dict, cold_result: dict) -> dict:
        """Select one meaningful structured event from a completed doll session."""
        candidates: list[tuple[str, dict]] = []
        canon_text = " ".join(
            str(item.get("fact_text", ""))
            for item in session.get("canon_written", [])
            if isinstance(item, dict)
        )
        canon_values = {
            asset["event_value"]
            for asset in self.catalog.assets
            if asset["event_key"] == "canon_choice"
        }
        for value in sorted(canon_values):
            if value in canon_text:
                candidates.append(("canon_choice", {"choice": value}))
                break

        produced = list(session.get("produced", []))
        produced.extend(
            item.get("word", "")
            for item in cold_result.get("mastery_updates", [])
            if item.get("result") == "produced"
        )
        word_values = {
            asset["event_value"]
            for asset in self.catalog.assets
            if asset["event_key"] == "word_taught"
        }
        for word in produced:
            if word in word_values:
                candidates.append(("word_taught", {"word": word}))
                break

        if not candidates:
            return {"status": "skipped", "reason": "insignificant"}
        event_key, payload = candidates[0]
        return self.settle_candidate(
            session["child_id"],
            "session",
            str(session["db_id"]),
            event_key,
            payload,
        )

    @staticmethod
    def _card(child_id: int, card_type: str) -> dict:
        row = db.q1(
            "SELECT payload_json FROM core_cards WHERE child_id=? AND type=?",
            (child_id, card_type),
        )
        return db.jloads(row["payload_json"], {}) if row else {}

    @staticmethod
    def _child(child_id: int) -> dict:
        return db.q1("SELECT * FROM children WHERE id=?", (child_id,)) or {}

    def child_world_now(
        self, child_id: int, *, now: datetime | None = None
    ) -> dict:
        current = _aware(now or self.now()).astimezone(self.zone)
        doll = self._card(child_id, "doll")
        child = self._child(child_id)
        doll_id = str(doll.get("id") or f"ling-{child_id}")
        selected = self.catalog.select_world_event(
            doll_id, current, self.timezone
        )
        raw_event = selected["event"]
        event = {
            "event_id": raw_event["event_id"],
            "event_version": raw_event["event_version"],
            "variant_id": raw_event["variant_id"],
            "title": raw_event["title"],
            "summary": raw_event["summary"],
            "timeline": raw_event.get("timeline", []),
            "media": raw_event["media"],
        }
        known_days = 1
        try:
            created = datetime.fromisoformat(child.get("created_at", ""))
            known_days = max(1, (current.date() - created.date()).days + 1)
        except (TypeError, ValueError):
            pass
        counts = db.q1(
            "SELECT COUNT(*) AS moments FROM moments WHERE child_id=? AND status='published'",
            (child_id,),
        ) or {"moments": 0}
        keepsakes = db.q1(
            "SELECT COUNT(*) AS n FROM pocket_entries WHERE child_id=? AND collected=1",
            (child_id,),
        ) or {"n": 0}
        return {
            "mode": selected["mode"],
            "timezone": selected["timezone"],
            "next_transition_at": selected["next_transition_at"],
            "doll": {
                "id": doll_id,
                "name": doll.get("name", "灵灵"),
                "known_days": known_days,
            },
            "event": event,
            "sleep_message": "灵灵要睡了，橡树村明早再见。"
            if selected["mode"] == "sleeping"
            else None,
            "memory_summary": {
                "moments": counts["moments"],
                "keepsakes": keepsakes["n"],
            },
        }

    def child_feed(
        self, child_id: int, *, now: datetime | None = None
    ) -> dict:
        current = _aware(now or self.now()).astimezone(self.zone)
        world = self.child_world_now(child_id, now=current)
        event = world["event"]
        public_item = {
            "id": f'public:{event["event_id"]}:{event["event_version"]}',
            "kind": "public",
            "status": "published",
            "title": event["title"],
            "summary": event["summary"],
            "occurred_at": _iso(current),
            "media": event["media"],
        }
        personal = self.personal_feed(child_id)
        items = [public_item, *personal["items"]]
        items.sort(key=lambda item: item.get("occurred_at", ""), reverse=True)
        return {"items": items, "pending": personal["pending"]}

    def _sessions_on(self, child_id: int, date: str) -> list[dict]:
        return db.q(
            "SELECT started_at,ended_at,cold_result_json FROM sessions "
            "WHERE child_id=? AND substr(started_at,1,10)=?",
            (child_id, date),
        )

    @staticmethod
    def _duration_minutes(sessions: list[dict], current: datetime) -> int:
        seconds = 0.0
        for session in sessions:
            try:
                start = datetime.fromisoformat(session["started_at"])
                end = datetime.fromisoformat(session["ended_at"]) if session["ended_at"] else current.replace(tzinfo=None)
            except (TypeError, ValueError):
                continue
            seconds += max(0.0, (end - start).total_seconds())
        return round(seconds / 60)

    def parent_today(
        self, child_id: int, *, now: datetime | None = None
    ) -> dict:
        current = _aware(now or self.now()).astimezone(self.zone)
        date = current.date().isoformat()
        child = self._child(child_id)
        doll = self._card(child_id, "doll")
        sessions = self._sessions_on(child_id, date)
        diaries = db.q(
            "SELECT summary,emotions_json,topics_json FROM diary_entries "
            "WHERE child_id=? AND substr(ts,1,10)=? ORDER BY ts DESC",
            (child_id, date),
        )
        latest = diaries[0] if diaries else db.q1(
            "SELECT summary,emotions_json,topics_json FROM diary_entries "
            "WHERE child_id=? ORDER BY ts DESC LIMIT 1",
            (child_id,),
        )
        topics = {
            topic
            for diary in diaries
            for topic in db.jloads(diary.get("topics_json"))
        }
        emotions = db.jloads(latest.get("emotions_json")) if latest else []
        mood_words = "、".join(emotions[:2]) if emotions else "平静"
        new_words = db.q1(
            "SELECT COUNT(*) AS n FROM item_mastery WHERE child_id=? "
            "AND level='produced' AND substr(last_seen,1,10)=?",
            (child_id, date),
        )["n"]
        next_item = db.q1(
            "SELECT item_text,item_zh FROM item_mastery WHERE child_id=? AND due_date<=? "
            "ORDER BY due_date,item_id LIMIT 1",
            (child_id, date),
        )
        return {
            "date": date,
            "child_display_name": child.get("name", "孩子"),
            "doll_display_name": doll.get("name", "灵灵"),
            "metrics": {
                "minutes_together": self._duration_minutes(sessions, current),
                "topics_count": len(topics),
                "new_words_spoken": new_words,
            },
            "mood": {
                "summary": f"最近一次谈话整体{mood_words}。这只是基于文字内容的粗略回顾。",
                "disclaimer": "大致参考，非诊断",
            },
            "attention": None,
            "tonight": {
                "summary": f'下次可以顺着灵灵的生活自然带出 {next_item["item_text"]}（{next_item["item_zh"]}）。'
            }
            if next_item
            else None,
        }

    def _growth_moments(self, child_id: int) -> list[dict]:
        rows = db.q(
            "SELECT old.text AS before,new.text AS after,new.created_at "
            "FROM facts old JOIN facts new ON new.id=old.superseded_by "
            "WHERE old.child_id=? ORDER BY new.created_at DESC",
            (child_id,),
        )
        return [{"before": row["before"], "after": row["after"]} for row in rows]

    def parent_growth(
        self,
        child_id: int,
        *,
        period: str = "week",
        now: datetime | None = None,
    ) -> dict:
        current = _aware(now or self.now()).astimezone(self.zone)
        words = db.q(
            "SELECT item_text,item_zh,level FROM item_mastery WHERE child_id=? "
            "AND item_type='word' AND level IN ('exposed','recognized','produced') "
            "ORDER BY CASE level WHEN 'produced' THEN 0 WHEN 'recognized' THEN 1 ELSE 2 END,item_id",
            (child_id,),
        )
        display_words = [
            {"text": row["item_text"], "meaning": row["item_zh"], "level": row["level"]}
            for row in words
        ]
        next_item = db.q1(
            "SELECT item_text,item_zh FROM item_mastery WHERE child_id=? AND due_date<=? "
            "ORDER BY due_date,item_id LIMIT 1",
            (child_id, current.date().isoformat()),
        )
        sessions = db.q(
            "SELECT cold_result_json FROM sessions WHERE child_id=? AND started_at>=?",
            (child_id, (current - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")),
        )
        spoken_attempts = sum(
            1
            for session in sessions
            for update in db.jloads(session["cold_result_json"], {}).get("mastery_updates", [])
            if update.get("result") == "produced"
        )
        return {
            "period_label": "本周" if period == "week" else period,
            "metrics": {
                "spoken_attempts": spoken_attempts,
                "new_words": len(display_words),
                "mastered_words": sum(1 for word in display_words if word["level"] == "produced"),
            },
            "words": display_words,
            "next_review": {
                "summary": f'下次会把 {next_item["item_text"]} 自然织进灵灵的生活。'
            }
            if next_item
            else None,
            "retreat": None,
            "growth_moments": self._growth_moments(child_id),
        }

    def parent_memory(
        self,
        child_id: int,
        *,
        cursor: str | None = None,
        limit: int = 20,
        now: datetime | None = None,
    ) -> dict:
        del now
        timeline: list[dict] = []
        for moment in db.q(
            "SELECT id,title,story,published_at FROM moments "
            "WHERE child_id=? AND status='published' ORDER BY published_at DESC",
            (child_id,),
        ):
            timeline.append(
                {
                    "id": f'moment:{moment["id"]}',
                    "occurred_at": moment["published_at"],
                    "label": "专属瞬间",
                    "kind": "moment",
                    "title": moment["title"],
                    "summary": moment["story"],
                }
            )
        for diary in db.q(
            "SELECT id,ts,summary,topics_json FROM diary_entries "
            "WHERE child_id=? ORDER BY ts DESC LIMIT 20",
            (child_id,),
        ):
            topics = db.jloads(diary["topics_json"])
            timeline.append(
                {
                    "id": f'attention:{diary["id"]}',
                    "occurred_at": diary["ts"],
                    "label": "共同经历",
                    "kind": "attention",
                    "title": "、".join(topics[:2]) if topics else "一次谈心",
                    "summary": diary["summary"],
                }
            )
        for index, row in enumerate(
            db.q(
                "SELECT old.text AS before,new.text AS after,new.created_at "
                "FROM facts old JOIN facts new ON new.id=old.superseded_by "
                "WHERE old.child_id=? ORDER BY new.created_at DESC",
                (child_id,),
            )
        ):
            timeline.append(
                {
                    "id": f"growth:{index + 1}",
                    "occurred_at": row["created_at"],
                    "label": "成长",
                    "kind": "growth",
                    "title": "记住变化后的你",
                    "summary": "一件以前会担心的事，现在已经有了新的答案。",
                    "before": row["before"],
                    "after": row["after"],
                }
            )
        timeline.sort(key=lambda item: item["occurred_at"] or "", reverse=True)
        try:
            offset = max(0, int(cursor or 0))
        except ValueError:
            offset = 0
        page = timeline[offset : offset + max(1, min(limit, 50))]
        next_offset = offset + len(page)
        child = self._child(child_id)
        return {
            "items": page,
            "next_cursor": str(next_offset) if next_offset < len(timeline) else None,
            "boundary_summary": {
                "red_lines": db.jloads(child.get("taboo_json"))
            },
            "rights": {
                "export_available": False,
                "deletion_request_available": False,
                "status_note": "黑客松版本仅展示数据权利说明，不执行导出或注销。",
            },
        }

    def parent_guardian(
        self, child_id: int, *, now: datetime | None = None
    ) -> dict:
        current = _aware(now or self.now()).astimezone(self.zone)
        child = self._child(child_id)
        today = self.parent_today(child_id, now=current)
        return {
            "availability_windows": [
                {"label": "放学后", "start": "16:00", "end": "19:00"},
                {"label": "睡前夜灯", "start": "20:00", "end": "21:00"},
            ],
            "daily_limit_minutes": 40,
            "used_today_minutes": today["metrics"]["minutes_together"],
            "bedtime": "21:00",
            "device": {"sleep_switch_label": "物理休眠", "status": "醒着"},
            "red_lines": db.jloads(child.get("taboo_json")),
            "ai_identity": {
                "message": "灵灵是 AI 学习伙伴，孵化时与使用中会定期说明。",
                "fixed": True,
            },
            "notifications": {
                "sms": "只发送安全与设备提醒",
                "card": "每晚至多一条摘要",
                "child_push": "每天至多一条，只在放学窗口",
            },
        }


_DEFAULT_SERVICE: ExperienceService | None = None


def default_service(*, reload: bool = False) -> ExperienceService:
    global _DEFAULT_SERVICE
    if reload or _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = ExperienceService()
    return _DEFAULT_SERVICE


def settle_candidate(
    child_id: int,
    source_type: str,
    source_id: str,
    event_key: str,
    payload: dict,
) -> dict:
    return default_service().settle_candidate(
        child_id, source_type, source_id, event_key, payload
    )
