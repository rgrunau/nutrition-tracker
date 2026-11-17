"""
Offline tests: prove the parsing and storage logic against a saved copy
of the real 'Stats' grid. No network, no Google credentials.
"""
import json
from datetime import date
from pathlib import Path

import pytest

import db
import tracker

SAMPLE = json.loads((Path(__file__).with_name("sample_grid.json")).read_text())
CFG = {"week": {"ending_weekday": 0}, "sheet": {}, "paths": {}}


# ---- string helpers -------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("8.5", 8.5), ("12,677", 12677.0), ("", None), ("Rest Day", None), (None, None),
])
def test_to_float(text, expected):
    assert tracker.to_float(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("7:57", 7.95), ("6:08", pytest.approx(6.133, abs=1e-3)), ("7.5", 7.5), ("", None),
])
def test_hhmm_to_hours(text, expected):
    assert tracker.hhmm_to_hours(text) == expected


# ---- layout detection ---------------------------------------------------

def test_find_layout():
    header, cols, day_rows, totals = tracker.find_layout(SAMPLE)
    assert header[8] == "Weight" and header[10] == "Steps"
    assert cols["weight"] == 8 and cols["steps"] == 10 and cols["week_ending"] == 9
    assert [d for d, _ in day_rows] == tracker.WEEKDAYS
    assert totals is not None and totals[8] == "166.74"


def test_find_layout_survives_leading_blank_rows():
    padded = [[""] * 11, [""] * 11] + SAMPLE
    header, cols, day_rows, totals = tracker.find_layout(padded)
    assert len(day_rows) == 7 and totals[10] == "9,574"


# ---- parsing ----------------------------------------------------------

def test_parse_daily():
    _, cols, day_rows, _ = tracker.find_layout(SAMPLE)
    daily = tracker.parse_daily(cols, day_rows)
    assert len(daily) == 7
    mon = daily[0]
    assert mon == {
        "day": "Monday", "protein": 8.5, "carb": 9.0, "fat": 5.0, "veggies": 3.0,
        "sleep": 7.95, "energy": 4.0, "training": "Muscular Endurance - Upper",
        "weight": 168.4, "steps": 8686,
    }
    assert daily[5]["weight"] is None       # Saturday weight blank
    assert daily[6]["steps"] == 6568


def test_parse_weekly_prefers_totals_row():
    _, cols, day_rows, totals = tracker.find_layout(SAMPLE)
    daily = tracker.parse_daily(cols, day_rows)
    weekly = tracker.parse_weekly(cols, totals, daily)
    assert weekly["weight_avg"] == 166.74     # straight from the totals row
    assert weekly["steps_avg"] == 9574
    assert weekly["protein_total"] == 56.5
    assert weekly["carb_total"] == 72.5
    assert weekly["fat_total"] == 34.0
    assert weekly["veggies_total"] == 22.0
    assert weekly["sleep_avg"] == pytest.approx(7.63, abs=0.02)   # computed
    assert weekly["energy_avg"] == pytest.approx(3.64, abs=0.02)  # computed


def test_parse_weekly_trusts_totals_row_rather_than_recomputing():
    _, cols, day_rows, totals = tracker.find_layout(SAMPLE)
    daily = tracker.parse_daily(cols, day_rows)
    doctored = list(totals)
    doctored[cols["weight"]] = "160.0"       # deliberately not the real average
    weekly = tracker.parse_weekly(cols, doctored, daily)
    assert weekly["weight_avg"] == 160.0     # took the sheet's value as-is


def test_parse_weekly_falls_back_without_totals_row():
    _, cols, day_rows, _ = tracker.find_layout(SAMPLE)
    daily = tracker.parse_daily(cols, day_rows)
    weekly = tracker.parse_weekly(cols, None, daily)
    # mean of the 5 filled daily weights (168.4, 166, 167.1, 166.4, 165.8)
    assert weekly["weight_avg"] == pytest.approx(166.74, abs=0.01)
    assert weekly["protein_total"] == 56.5   # sum of the 7 daily portions


def test_parse_targets():
    header, cols, _, _ = tracker.find_layout(SAMPLE)
    targets = {t["label"]: t for t in tracker.parse_targets(header, cols)}
    assert targets["Protein"] == {
        "label": "Protein", "unit": "palm", "low": 42.0, "high": 56.0,
        "raw": "Protein (palm) 42-56",
    }
    assert targets["Veggies"]["low"] == 25.0 and targets["Veggies"]["high"] is None


def test_parse_backfill():
    _, cols, day_rows, _ = tracker.find_layout(SAMPLE)
    rows = tracker.parse_backfill(day_rows, cols, date(2026, 8, 31))
    assert rows == [
        {"week_ending": "2026-08-11", "weight_avg": 165.3},
        {"week_ending": "2026-08-18", "weight_avg": 165.8},
        {"week_ending": "2026-08-25", "weight_avg": 166.2},
    ]


@pytest.mark.parametrize("weekday, today, expected", [
    (0, date(2026, 8, 31), date(2026, 8, 31)),   # a Monday -> itself
    (0, date(2026, 9, 3), date(2026, 8, 31)),    # Thursday -> back to Monday
    (6, date(2026, 8, 31), date(2026, 8, 30)),   # Sunday convention
])
def test_week_ending_for(weekday, today, expected):
    assert tracker.week_ending_for(today, weekday) == expected


# ---- end to end (real SQLite in a temp dir) --------------------------

def _cfg(tmp_path):
    return {
        "week": {"ending_weekday": 0},
        "sheet": {},
        "paths": {
            "database": str(tmp_path / "history.db"),
            "csv_dir": str(tmp_path / "csv"),
        },
    }


def test_run_writes_and_is_idempotent(tmp_path):
    cfg = _cfg(tmp_path)
    today = date(2026, 8, 31)

    first = tracker.run(SAMPLE, cfg, today=today)
    assert first["status"] == "inserted"
    assert first["week_ending"] == "2026-08-31"
    assert sorted(first["backfilled"]) == ["2026-08-11", "2026-08-18", "2026-08-25"]

    second = tracker.run(SAMPLE, cfg, today=today)
    assert second["status"] == "updated"
    assert second["backfilled"] == []            # already there, not duplicated

    conn = db.connect(cfg["paths"]["database"])
    weeks = conn.execute(
        "SELECT week_ending, source FROM weekly_summary ORDER BY week_ending"
    ).fetchall()
    assert [tuple(r) for r in weeks] == [
        ("2026-08-11", "backfill"),
        ("2026-08-18", "backfill"),
        ("2026-08-25", "backfill"),
        ("2026-08-31", "sheet"),
    ]
    assert conn.execute("SELECT COUNT(*) FROM daily_snapshot").fetchone()[0] == 7
    assert conn.execute("SELECT COUNT(*) FROM targets").fetchone()[0] == 4
    conn.close()

    assert (tmp_path / "csv" / "weekly_summary.csv").exists()
    assert (tmp_path / "csv" / "daily_snapshot.csv").exists()


def test_backfill_never_clobbers_a_real_row(tmp_path):
    cfg = _cfg(tmp_path)
    conn = db.connect(cfg["paths"]["database"])
    db.upsert_weekly(conn, {"week_ending": "2026-08-25", "weight_avg": 999.0},
                     source="sheet")
    conn.close()

    tracker.run(SAMPLE, cfg, today=date(2026, 8, 31))

    conn = db.connect(cfg["paths"]["database"])
    row = conn.execute(
        "SELECT weight_avg, source FROM weekly_summary WHERE week_ending = '2026-08-25'"
    ).fetchone()
    assert tuple(row) == (999.0, "sheet")        # backfill left it alone
    conn.close()


def test_dry_run_writes_nothing(tmp_path):
    cfg = _cfg(tmp_path)
    result = tracker.run(SAMPLE, cfg, today=date(2026, 8, 31), write=False)
    assert result["status"] == "dry-run"
    assert not (tmp_path / "history.db").exists()
