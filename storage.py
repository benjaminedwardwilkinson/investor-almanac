"""SQLite cache for official data observations and source freshness."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DATABASE


@contextmanager
def connect(db_path: str = DATABASE):
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    db = sqlite3.connect(db_path, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db(db_path: str = DATABASE) -> None:
    with connect(db_path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                source_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                retrieved_at TEXT,
                attempted_at TEXT,
                last_error TEXT
            );
            CREATE TABLE IF NOT EXISTS observations (
                source_key TEXT NOT NULL REFERENCES sources(source_key),
                series_key TEXT NOT NULL,
                period TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                PRIMARY KEY (source_key, series_key, period)
            );
            CREATE INDEX IF NOT EXISTS observations_series_period
                ON observations(series_key, period);
            CREATE TABLE IF NOT EXISTS news_stories (
                source_key TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                published TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                PRIMARY KEY (source_key, url)
            );
            """
        )


def save_source(source_key: str, metadata: dict, observations: list[dict], retrieved_at: str, db_path: str = DATABASE) -> int:
    if not observations:
        raise ValueError(f"No observations to save for {source_key}")
    with connect(db_path) as db:
        db.execute(
            "INSERT INTO sources(source_key,title,url,retrieved_at,attempted_at,last_error) VALUES(?,?,?,?,?,NULL) "
            "ON CONFLICT(source_key) DO UPDATE SET title=excluded.title,url=excluded.url,"
            "retrieved_at=excluded.retrieved_at,attempted_at=excluded.attempted_at,last_error=NULL",
            (source_key, metadata["title"], metadata["url"], retrieved_at, retrieved_at),
        )
        db.executemany(
            "INSERT INTO observations(source_key,series_key,period,value,unit,retrieved_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(source_key,series_key,period) DO UPDATE SET value=excluded.value,unit=excluded.unit,retrieved_at=excluded.retrieved_at",
            [(source_key, row["series_key"], row["period"], row["value"], row["unit"], retrieved_at) for row in observations],
        )
    return len(observations)


def save_news(source_key: str, metadata: dict, stories: list[dict], retrieved_at: str, db_path: str = DATABASE) -> int:
    with connect(db_path) as db:
        db.execute(
            "INSERT INTO sources(source_key,title,url,retrieved_at,attempted_at,last_error) VALUES(?,?,?,?,?,NULL) "
            "ON CONFLICT(source_key) DO UPDATE SET title=excluded.title,url=excluded.url,retrieved_at=excluded.retrieved_at,attempted_at=excluded.attempted_at,last_error=NULL",
            (source_key, metadata["title"], metadata["url"], retrieved_at, retrieved_at),
        )
        db.executemany(
            "INSERT INTO news_stories(source_key,url,title,summary,published,retrieved_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(source_key,url) DO UPDATE SET title=excluded.title,summary=excluded.summary,published=excluded.published,retrieved_at=excluded.retrieved_at",
            [(source_key, item["url"], item["title"], item.get("summary", ""), item.get("published", ""), retrieved_at) for item in stories],
        )
        # Keep the small cache bounded while retaining stories across short feed outages.
        db.execute("DELETE FROM news_stories WHERE source_key=? AND url NOT IN (SELECT url FROM news_stories WHERE source_key=? ORDER BY retrieved_at DESC LIMIT 40)", (source_key, source_key))
    return len(stories)


def recent_news(source_key: str, limit: int = 6, db_path: str = DATABASE) -> list[dict]:
    with connect(db_path) as db:
        rows = db.execute("SELECT title,summary,url,published,retrieved_at FROM news_stories WHERE source_key=? ORDER BY retrieved_at DESC,published DESC LIMIT ?", (source_key, limit)).fetchall()
    return [dict(row) for row in rows]


def save_error(source_key: str, metadata: dict, message: str, attempted_at: str, db_path: str = DATABASE) -> None:
    with connect(db_path) as db:
        db.execute(
            "INSERT INTO sources(source_key,title,url,attempted_at,last_error) VALUES(?,?,?,?,?) "
            "ON CONFLICT(source_key) DO UPDATE SET title=excluded.title,url=excluded.url,"
            "attempted_at=excluded.attempted_at,last_error=excluded.last_error",
            (source_key, metadata["title"], metadata["url"], attempted_at, message[:500]),
        )


def series(series_key: str, db_path: str = DATABASE) -> list[dict]:
    with connect(db_path) as db:
        rows = db.execute(
            "SELECT period,value,unit,retrieved_at FROM observations WHERE series_key=? ORDER BY period",
            (series_key,),
        ).fetchall()
    return [dict(row) for row in rows]


def all_series(db_path: str = DATABASE) -> dict[str, list[dict]]:
    with connect(db_path) as db:
        rows = db.execute("SELECT series_key,period,value,unit,retrieved_at FROM observations ORDER BY series_key,period").fetchall()
    result: dict[str, list[dict]] = {}
    for row in rows:
        result.setdefault(row["series_key"], []).append({key: row[key] for key in ("period", "value", "unit", "retrieved_at")})
    return result


def source_status(db_path: str = DATABASE) -> list[dict]:
    with connect(db_path) as db:
        rows = db.execute(
            "SELECT s.source_key,s.title,s.url,s.retrieved_at,s.attempted_at,s.last_error,"
            "MAX(o.period) AS latest_period,COUNT(o.period) AS observation_count "
            "FROM sources s LEFT JOIN observations o ON o.source_key=s.source_key "
            "GROUP BY s.source_key ORDER BY s.title"
        ).fetchall()
    return [dict(row) for row in rows]


def latest_period(series_key: str, db_path: str = DATABASE) -> dict | None:
    with connect(db_path) as db:
        row = db.execute(
            "SELECT period,value,unit,retrieved_at FROM observations WHERE series_key=? ORDER BY period DESC LIMIT 1",
            (series_key,),
        ).fetchone()
    return dict(row) if row else None
