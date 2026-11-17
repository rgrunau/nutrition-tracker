"""
Storage layer: a small SQLite database plus CSV mirrors.

Design notes
------------
* SQLite is the source of truth. It gives us a primary key per week, so
  re-running the tool updates a week in place instead of duplicating it.
* The CSV files are throwaway views, rewritten from the database on every
  run. Open them in any spreadsheet; never edit them by hand.
* Every function takes an open connection so tests can pass an in-memory DB.
"""

from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS weekly_summary (
    week_ending   TEXT PRIMARY KEY,          -- ISO date, e.g. '2026-08-31'
    weight_avg    REAL,
    steps_avg     INTEGER,
    protein_total REAL,
    carb_total    REAL,
    fat_total     REAL,
    veggies_total REAL,
    sleep_avg     REAL,
    energy_avg    REAL,
    source        TEXT NOT NULL DEFAULT 'sheet',  -- 'sheet' or 'backfill'
    pulled_at     TEXT NOT NULL              -- ISO timestamp, UTC
);

CREATE TABLE IF NOT EXISTS daily_snapshot (
    week_ending TEXT NOT NULL,
    day         TEXT NOT NULL,               -- 'Monday' ... 'Sunday'
    protein     REAL,
    carb        REAL,
    fat         REAL,
    veggies     REAL,
    sleep       REAL,                        -- hours as a decimal (7:30 -> 7.5)
    energy      REAL,
    training    TEXT,
    weight      REAL,
    steps       INTEGER,
    PRIMARY KEY (week_ending, day)
);

CREATE TABLE IF NOT EXISTS targets (
    label      TEXT PRIMARY KEY,             -- 'Protein'
    unit       TEXT,                         -- 'palm'
    low        REAL,
    high       REAL,
    raw        TEXT NOT NULL,                -- original header cell text
    updated_at TEXT NOT NULL
);
"""

WEEKLY_COLUMNS = [
    "week_ending", "weight_avg", "steps_avg", "protein_total", "carb_total",
    "fat_total", "veggies_total", "sleep_avg", "energy_avg", "source", "pulled_at",
]

DAILY_COLUMNS = [
    "week_ending", "day", "protein", "carb", "fat", "veggies", "sleep",
    "energy", "training", "weight", "steps",
]


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the database and ensure the schema exists."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_weekly(conn: sqlite3.Connection, row: dict, *, source: str = "sheet") -> str:
    """
    Insert or update one weekly_summary row, keyed on week_ending.

    Returns 'inserted', 'updated', or 'skipped'.

    A 'backfill' row (recovered from the coach's manual log) must never
    overwrite a real 'sheet' snapshot, so it only fills gaps.
    """
    values = dict(row)
    values["source"] = source
    values["pulled_at"] = _now_iso()

    existing = conn.execute(
        "SELECT source FROM weekly_summary WHERE week_ending = ?",
        (values["week_ending"],),
    ).fetchone()

    if existing and source == "backfill":
        return "skipped"

    cols = ", ".join(WEEKLY_COLUMNS)
    placeholders = ", ".join(f":{c}" for c in WEEKLY_COLUMNS)
    updates = ", ".join(f"{c} = excluded.{c}" for c in WEEKLY_COLUMNS if c != "week_ending")
    conn.execute(
        f"INSERT INTO weekly_summary ({cols}) VALUES ({placeholders}) "
        f"ON CONFLICT(week_ending) DO UPDATE SET {updates}",
        {c: values.get(c) for c in WEEKLY_COLUMNS},
    )
    conn.commit()
    return "updated" if existing else "inserted"


def replace_daily(conn: sqlite3.Connection, week_ending: str, days: list[dict]) -> None:
    """Wipe and rewrite the 7 daily rows for a week (keeps re-runs clean)."""
    conn.execute("DELETE FROM daily_snapshot WHERE week_ending = ?", (week_ending,))
    conn.executemany(
        f"INSERT INTO daily_snapshot ({', '.join(DAILY_COLUMNS)}) "
        f"VALUES ({', '.join('?' for _ in DAILY_COLUMNS)})",
        [
            [week_ending if c == "week_ending" else d.get(c) for c in DAILY_COLUMNS]
            for d in days
        ],
    )
    conn.commit()


def upsert_targets(conn: sqlite3.Connection, targets: list[dict]) -> None:
    """Store the header-row budget ranges. Overwrites by label."""
    now = _now_iso()
    conn.executemany(
        "INSERT INTO targets (label, unit, low, high, raw, updated_at) "
        "VALUES (:label, :unit, :low, :high, :raw, :updated_at) "
        "ON CONFLICT(label) DO UPDATE SET unit=excluded.unit, low=excluded.low, "
        "high=excluded.high, raw=excluded.raw, updated_at=excluded.updated_at",
        [{**t, "updated_at": now} for t in targets],
    )
    conn.commit()


def export_csv(conn: sqlite3.Connection, csv_dir: str | Path) -> list[Path]:
    """Rewrite the CSV mirrors from the current database contents."""
    out_dir = Path(csv_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, order in (
        ("weekly_summary", "week_ending"),
        ("daily_snapshot", "week_ending, "
         "CASE day WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 WHEN 'Wednesday' THEN 3 "
         "WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 WHEN 'Saturday' THEN 6 "
         "WHEN 'Sunday' THEN 7 ELSE 8 END"),
        ("targets", "label"),
    ):
        rows = conn.execute(f"SELECT * FROM {name} ORDER BY {order}").fetchall()
        path = out_dir / f"{name}.csv"
        with path.open("w", newline="") as fh:
            writer = csv.writer(fh)
            if rows:
                writer.writerow(rows[0].keys())
                writer.writerows([list(r) for r in rows])
            else:
                # Still emit a header-only file so downstream tools don't choke.
                cols = [c[1] for c in conn.execute(f"PRAGMA table_info({name})")]
                writer.writerow(cols)
        written.append(path)
    return written
