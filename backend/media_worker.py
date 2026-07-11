"""Recoverable background driver for persisted external media jobs."""

from __future__ import annotations

import argparse
import os
import threading
import time

from . import db, experience


class MediaGenerationWorker:
    def __init__(
        self,
        service: experience.ExperienceService,
        *,
        interval_seconds: int = 2,
        batch_size: int = 10,
    ):
        self.service = service
        self.provider_name = service.provider.name
        self.interval_seconds = max(1, interval_seconds)
        self.batch_size = max(1, batch_size)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _moment_ids(self) -> list[int]:
        rows = db.q(
            "SELECT m.id FROM moments m "
            "JOIN generation_jobs j ON j.moment_id=m.id "
            "WHERE m.status='rendering' AND j.provider=? "
            "AND j.id=(SELECT id FROM generation_jobs latest "
            "WHERE latest.moment_id=m.id ORDER BY attempt DESC LIMIT 1) "
            "ORDER BY j.created_at LIMIT ?",
            (self.provider_name, self.batch_size),
        )
        return [int(row["id"]) for row in rows]

    def run_once(self) -> dict:
        moment_ids = self._moment_ids()
        processed = 0
        failed = 0
        for moment_id in moment_ids:
            try:
                self.service.refresh_moment(moment_id)
                processed += 1
            except Exception as exc:
                failed += 1
                print(
                    f"[media] moment={moment_id} worker error: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
        return {
            "provider": self.provider_name,
            "selected": len(moment_ids),
            "processed": processed,
            "errors": failed,
            "remaining": self.pending_count(),
        }

    def pending_count(self) -> int:
        row = db.q1(
            "SELECT COUNT(*) AS n FROM moments m WHERE m.status='rendering' "
            "AND EXISTS (SELECT 1 FROM generation_jobs j "
            "WHERE j.moment_id=m.id AND j.provider=?)",
            (self.provider_name,),
        )
        return int(row["n"] if row else 0)

    def _run(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self.interval_seconds)

    def start(self) -> bool:
        if self._thread and self._thread.is_alive():
            return False
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="ling-media-worker",
            daemon=True,
        )
        self._thread.start()
        return True

    @property
    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)


_DEFAULT_WORKER: MediaGenerationWorker | None = None


def worker_enabled() -> bool:
    return os.environ.get("LING_MEDIA_WORKER_ENABLED", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def start_default(
    service: experience.ExperienceService,
) -> MediaGenerationWorker | None:
    global _DEFAULT_WORKER
    if service.provider.name != "jimeng-ark" or not worker_enabled():
        return None
    if _DEFAULT_WORKER is None or _DEFAULT_WORKER.service is not service:
        if _DEFAULT_WORKER:
            _DEFAULT_WORKER.stop()
        interval = int(os.environ.get("LING_MEDIA_WORKER_INTERVAL_SECONDS", "2"))
        batch_size = int(os.environ.get("LING_MEDIA_WORKER_BATCH_SIZE", "10"))
        _DEFAULT_WORKER = MediaGenerationWorker(
            service,
            interval_seconds=interval,
            batch_size=batch_size,
        )
    _DEFAULT_WORKER.start()
    return _DEFAULT_WORKER


def stop_default() -> None:
    global _DEFAULT_WORKER
    if _DEFAULT_WORKER:
        _DEFAULT_WORKER.stop()
    _DEFAULT_WORKER = None


def default_worker() -> MediaGenerationWorker | None:
    return _DEFAULT_WORKER


def job_summaries(limit: int = 50) -> list[dict]:
    return db.q(
        "SELECT id,moment_id,attempt,provider,status,external_task_id,"
        "provider_failures,next_poll_at,error_code,asset_id,media_path,poster_path,"
        "created_at,updated_at,completed_at FROM generation_jobs "
        "ORDER BY id DESC LIMIT ?",
        (max(1, min(limit, 200)),),
    )


def _main() -> int:
    parser = argparse.ArgumentParser(description="Drive persisted Ling media jobs")
    parser.add_argument("--once", action="store_true", help="process one batch and exit")
    parser.add_argument(
        "--until-idle", action="store_true", help="poll until no rendering moments remain"
    )
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    db.init_db()
    service = experience.default_service(reload=True)
    worker = MediaGenerationWorker(service)
    if args.once or not args.until_idle:
        print(worker.run_once())
        return 0
    deadline = time.monotonic() + max(1, args.timeout)
    while time.monotonic() < deadline:
        result = worker.run_once()
        print(result, flush=True)
        if result["remaining"] == 0:
            return 0
        time.sleep(worker.interval_seconds)
    print({"error": "timeout", "remaining": worker.pending_count()})
    return 1


if __name__ == "__main__":
    raise SystemExit(_main())
