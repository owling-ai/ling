from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend import db


def _close_db_connection() -> None:
    conn = getattr(db._local, "conn", None)
    if conn is not None:
        conn.close()
        delattr(db._local, "conn")


@pytest.fixture
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _close_db_connection()
    path = tmp_path / "ling-test.db"
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init_db()
    yield path
    _close_db_connection()


@pytest.fixture
def db_connection(isolated_db: Path) -> sqlite3.Connection:
    return db.get_conn()
