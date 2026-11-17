#!/usr/bin/env python3
"""
nutrition-tracker — archive weekly stats from the coaching Google Sheet.

Pipeline:
    Google Sheet "Stats" tab
        -> get_all_values()  (a list of rows, each a list of strings)
        -> find_layout()     locate header, the 7 day rows, the totals row
        -> parse_*()         turn strings into numbers
        -> db.upsert_*()     write into SQLite, keyed by week-ending date
        -> db.export_csv()   refresh the plain-text mirrors

Everything above the Google call is pure string-in / dict-out, so the
parsing is unit-tested with a saved copy of the grid and no network.

Usage:
    python tracker.py                      # pull the live sheet, store it
    python tracker.py --dry-run            # parse and print, write nothing
    python tracker.py --from-json grid.json  # parse a saved grid (offline)
    python tracker.py --week-ending 2026-08-31   # force the file-under date
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from datetime import date, timedelta
from pathlib import Path

import db

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday",
            "Friday", "Saturday", "Sunday"]


# --------------------------------------------------------------------------
# tiny string -> number helpers
# --------------------------------------------------------------------------

def to_float(text: str | None) -> float | None:
    """'8.5' -> 8.5 ; '12,677' -> 12677.0 ; '' -> None ; 'Rest' -> None"""
    text = (text or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(text: str | None) -> int | None:
    f = to_float(text)
    return None if f is None else int(round(f))


def hhmm_to_hours(text: str | None) -> float | None:
    """'7:57' -> 7.95 hours ; '7.5' -> 7.5 ; '' -> None"""
    text = (text or "").strip()
    if not text:
        return None
    if ":" in text:
        h, _, m = text.partition(":")
        try:
            return round(int(h) + int(m) / 60, 3)
        except ValueError:
            return None
    return to_float(text)


def _cell(row: list[str], idx: int | None) -> str:
    """Safe indexing — trailing empty cells are often missing from a row."""
    if idx is None or idx >= len(row):
        return ""
    return row[idx]


def _avg(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    return round(sum(nums) / len(nums), 3) if nums else None


def _sum(values: list[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    return round(sum(nums), 3) if nums else None


# --------------------------------------------------------------------------
# layout detection + parsing
# --------------------------------------------------------------------------

COLUMN_KEYWORDS = {
    "protein": ["protein"],
    "carb": ["carb"],
    "fat": ["fat"],
    "veggies": ["veggie"],
    "sleep": ["sleep"],
    "energy": ["energy"],
    "training": ["training"],
    "weight": ["weight"],
    "week_ending": ["week ending", "week end"],
    "steps": ["step"],
}


def map_columns(header_row: list[str]) -> dict[str, int]:
    """Map our field names to column indexes by keyword-matching the header."""
    found: dict[str, int] = {}
    for i, cell in enumerate(header_row):
        low = (cell or "").strip().lower()
        if not low:
            continue
        for name, needles in COLUMN_KEYWORDS.items():
            if name not in found and any(n in low for n in needles):
                found[name] = i
    return found


def find_layout(grid: list[list[str]]):
    """
    Return (header_row, columns, day_rows, totals_row).

    * header_row  — the raw list of header cells
    * columns     — {field: column index}
    * day_rows    — [(canonical_day_name, raw_row), ...] length 7
    * totals_row  — the raw row holding weekly averages/sums (or None)

    Located by content, not fixed coordinates, so inserting a blank row
    at the top of the sheet doesn't break it.
    """
    header_idx = None
    for idx, row in enumerate(grid):
        low = [(c or "").strip().lower() for c in row]
        if "weight" in low and any("step" in c for c in low):
            header_idx = idx
            break
    if header_idx is None:
        raise ValueError("Could not find the header row (needs 'Weight' and 'Steps').")

    header_row = grid[header_idx]
    columns = map_columns(header_row)

    day_rows: list[tuple[str, list[str]]] = []
    r = header_idx + 1
    while r < len(grid):
        first = (_cell(grid[r], 0)).strip().lower()
        match = next((d for d in WEEKDAYS if first.startswith(d.lower())), None)
        if match:
            day_rows.append((match, grid[r]))
        elif day_rows:
            break            # we've walked past the 7-day block
        r += 1

    if len(day_rows) != 7:
        raise ValueError(f"Expected 7 day rows after the header, found {len(day_rows)}.")

    totals_row = None
    while r < len(grid):
        row = grid[r]
        if (to_float(_cell(row, columns.get("weight"))) is not None
                or to_float(_cell(row, columns.get("steps"))) is not None):
            totals_row = row
            break
        r += 1

    return header_row, columns, day_rows, totals_row


def parse_daily(columns: dict[str, int],
                day_rows: list[tuple[str, list[str]]]) -> list[dict]:
    out = []
    for day, row in day_rows:
        training = _cell(row, columns.get("training")).strip()
        out.append({
            "day": day,
            "protein": to_float(_cell(row, columns.get("protein"))),
            "carb": to_float(_cell(row, columns.get("carb"))),
            "fat": to_float(_cell(row, columns.get("fat"))),
            "veggies": to_float(_cell(row, columns.get("veggies"))),
            "sleep": hhmm_to_hours(_cell(row, columns.get("sleep"))),
            "energy": to_float(_cell(row, columns.get("energy"))),
            "training": training or None,
            "weight": to_float(_cell(row, columns.get("weight"))),
            "steps": to_int(_cell(row, columns.get("steps"))),
        })
    return out


def parse_weekly(columns: dict[str, int],
                 totals_row: list[str] | None,
                 daily: list[dict]) -> dict:
    """
    Headline numbers. The totals row in the sheet already holds the
    weekly average weight, average steps, and portion sums — prefer those.
    Sleep and energy have no totals cell, so we average the 7 days.
    Everything falls back to a computed value if the totals row is absent.
    """
    def total_or(field: str, fallback):
        if totals_row is not None:
            v = to_float(_cell(totals_row, columns.get(field)))
            if v is not None:
                return v
        return fallback

    steps_avg = None
    if totals_row is not None:
        steps_avg = to_int(_cell(totals_row, columns.get("steps")))
    if steps_avg is None:
        avg = _avg([d["steps"] for d in daily])
        steps_avg = int(round(avg)) if avg is not None else None

    return {
        "weight_avg": total_or("weight", _avg([d["weight"] for d in daily])),
        "steps_avg": steps_avg,
        "protein_total": total_or("protein", _sum([d["protein"] for d in daily])),
        "carb_total": total_or("carb", _sum([d["carb"] for d in daily])),
        "fat_total": total_or("fat", _sum([d["fat"] for d in daily])),
        "veggies_total": total_or("veggies", _sum([d["veggies"] for d in daily])),
        "sleep_avg": _avg([d["sleep"] for d in daily]),
        "energy_avg": _avg([d["energy"] for d in daily]),
    }


TARGET_RE = re.compile(
    r"^(?P<label>[A-Za-z]+)\s*"
    r"(?:\((?P<unit>[^)]*)\)\s*)?"
    r"(?P<low>\d+(?:\.\d+)?)?\s*"
    r"(?:-\s*(?P<high>\d+(?:\.\d+)?))?"
    r"\+?\s*$"
)


def parse_targets(header_row: list[str], columns: dict[str, int]) -> list[dict]:
    """'Protein (palm) 42-56' -> {label:'Protein', unit:'palm', low:42, high:56}."""
    out = []
    for field in ("protein", "carb", "fat", "veggies"):
        idx = columns.get(field)
        if idx is None:
            continue
        raw = _cell(header_row, idx).strip()
        m = TARGET_RE.match(raw)
        unit = low = high = None
        if m:
            unit = (m.group("unit") or "").strip() or None
            low = float(m.group("low")) if m.group("low") else None
            high = float(m.group("high")) if m.group("high") else None
        out.append({"label": field.capitalize(), "unit": unit,
                    "low": low, "high": high, "raw": raw})
    return out


LOG_RE = re.compile(r"(?P<m>\d{1,2})/(?P<d>\d{1,2})\s*-\s*(?P<w>\d+(?:\.\d+)?)")


def parse_backfill(day_rows: list[tuple[str, list[str]]],
                   columns: dict[str, int],
                   reference: date) -> list[dict]:
    """
    Recover past weeks from the coach's hand-typed log in the
    'Week ending' column, e.g. '8/11 - 165.3'. Year is inferred from
    `reference` (a month later than today's month means last year).
    """
    col = columns.get("week_ending")
    if col is None:
        return []
    out = []
    for _day, row in day_rows:
        m = LOG_RE.search(_cell(row, col))
        if not m:
            continue
        month, day_num = int(m.group("m")), int(m.group("d"))
        year = reference.year - 1 if month > reference.month else reference.year
        try:
            when = date(year, month, day_num)
        except ValueError:
            continue
        out.append({"week_ending": when.isoformat(),
                    "weight_avg": float(m.group("w"))})
    return out


def week_ending_for(today: date, ending_weekday: int) -> date:
    """Most recent day (today or earlier) whose weekday == ending_weekday."""
    return today - timedelta(days=(today.weekday() - ending_weekday) % 7)


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------

def load_config(path: str | Path) -> dict:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def fetch_grid(cfg: dict) -> list[list[str]]:
    """The one function that talks to Google. Imported lazily so offline
    tests and --from-json never need the library or credentials."""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(
        cfg["paths"]["credentials"], scopes=scopes)
    worksheet = (gspread.authorize(creds)
                 .open_by_key(cfg["sheet"]["id"])
                 .worksheet(cfg["sheet"]["worksheet"]))
    return worksheet.get_all_values()


def run(grid: list[list[str]], cfg: dict, *,
        today: date | None = None,
        week_ending: str | None = None,
        do_backfill: bool = True,
        write: bool = True) -> dict:
    today = today or date.today()
    header_row, columns, day_rows, totals_row = find_layout(grid)

    daily = parse_daily(columns, day_rows)
    weekly = parse_weekly(columns, totals_row, daily)
    targets = parse_targets(header_row, columns)
    backfill = parse_backfill(day_rows, columns, today) if do_backfill else []

    we = week_ending or week_ending_for(
        today, cfg["week"]["ending_weekday"]).isoformat()
    weekly["week_ending"] = we

    result = {
        "week_ending": we,
        "weekly": weekly,
        "daily": daily,
        "targets": targets,
        "backfill_candidates": backfill,
        "status": "dry-run",
        "backfilled": [],
        "csv": [],
    }
    if not write:
        return result

    conn = db.connect(cfg["paths"]["database"])
    try:
        result["status"] = db.upsert_weekly(conn, weekly, source="sheet")
        db.replace_daily(conn, we, daily)
        if targets:
            db.upsert_targets(conn, targets)
        for row in backfill:
            if db.upsert_weekly(conn, row, source="backfill") == "inserted":
                result["backfilled"].append(row["week_ending"])
        result["csv"] = [str(p) for p in db.export_csv(conn, cfg["paths"]["csv_dir"])]
    finally:
        conn.close()
    return result


def print_summary(result: dict) -> None:
    w = result["weekly"]
    print(f"Week ending {result['week_ending']}  [{result['status']}]")
    print(f"  weight avg : {w['weight_avg']}")
    print(f"  steps avg  : {w['steps_avg']}")
    print(f"  portions   : P {w['protein_total']}  C {w['carb_total']}  "
          f"F {w['fat_total']}  V {w['veggies_total']}")
    print(f"  sleep avg  : {w['sleep_avg']} h     energy avg : {w['energy_avg']}")
    filled = sum(1 for d in result["daily"] if d["protein"] is not None)
    print(f"  daily rows : {filled}/7 have portion data")
    if result["backfilled"]:
        print(f"  backfilled : {', '.join(result['backfilled'])}")
    if result["csv"]:
        print(f"  wrote      : {', '.join(result['csv'])}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    default_cfg = Path(__file__).with_name("config.toml")
    p.add_argument("--config", default=str(default_cfg))
    p.add_argument("--from-json", metavar="FILE",
                   help="Parse a saved grid (JSON list-of-lists) instead of Google.")
    p.add_argument("--week-ending", metavar="YYYY-MM-DD",
                   help="Override the date this week is filed under.")
    p.add_argument("--no-backfill", action="store_true",
                   help="Don't parse the coach's manual log column.")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse and print a summary, but write nothing.")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    if args.from_json:
        grid = json.loads(Path(args.from_json).read_text())
    else:
        grid = fetch_grid(cfg)

    result = run(grid, cfg,
                 week_ending=args.week_ending,
                 do_backfill=not args.no_backfill,
                 write=not args.dry_run)
    print_summary(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
