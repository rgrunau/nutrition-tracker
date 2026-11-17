# nutrition-tracker

Pulls your weekly stats out of the coaching Google Sheet and keeps a permanent
local history, so the numbers don't vanish when next week overwrites the grid.

- **Source:** the `Stats` tab of the shared "Robert" sheet.
- **Store:** `data/history.db` (SQLite, the source of truth) + CSV mirrors in `data/`.
- **Captured per week:** average weight, average steps, portion totals
  (protein/carb/fat/veggies), average sleep, average energy, the full 7-day
  daily breakdown, and your header-row target ranges.

---

## How it works

```
Stats tab  --get_all_values()-->  [[strings], ...]
                                        |
              find_layout()  finds the header, 7 day rows, totals row
                                        |
              parse_*()      strings -> numbers
                                        |
              db.upsert_*()   write to SQLite, keyed on week-ending date
                                        |
              db.export_csv() rewrite the CSV mirrors
```

Writes are keyed on the **week-ending date**, so running it repeatedly for the
same week updates that one row instead of piling up duplicates. That makes the
weekly cron job and any manual runs safe to overlap.

---

## One-time setup

### 1. Python environment

```bash
cd ~/Work/nutrition-tracker
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Create a Google service account and key

A *service account* is a Google identity that belongs to this script, not to
you. It authenticates with a downloaded key file — no browser, no login prompt,
nothing that expires.

1. Go to <https://console.cloud.google.com/> and sign in with your Google
   account.
2. **Create a project:** top bar → project dropdown → *New Project* →
   name it `nutrition-tracker` → *Create*. Wait for it to switch to the new
   project (check the top bar).
3. **Enable the Sheets API:** search bar → "Google Sheets API" → *Enable*.
   (You do **not** need the Drive API — we open the sheet by its ID.)
4. **Create the service account:** search bar → "Service Accounts" →
   *Create Service Account*.
   - Name: `sheet-reader` → *Create and Continue*.
   - Skip the optional "grant access" steps → *Done*.
5. **Make a key:** click the new service account → *Keys* tab → *Add Key* →
   *Create new key* → **JSON** → *Create*. A `.json` file downloads.
6. Move that file into the project and give it the name the config expects:

   ```bash
   mv ~/Downloads/nutrition-tracker-*.json ~/Work/nutrition-tracker/credentials/service-account.json
   ```

   It's already git-ignored. Treat it like a password — anyone with this file
   can read anything the service account can read.

### 3. Share the sheet with the service account

1. Open `credentials/service-account.json` and copy the `"client_email"` value
   — it looks like `sheet-reader@nutrition-tracker-123456.iam.gserviceaccount.com`.
2. Open the "Robert" sheet in Google Sheets → **Share** → paste that address →
   set it to **Viewer** → untick "Notify people" → *Share*.

That's the whole handshake. The script can now read the sheet.

### 4. Confirm the config

`config.toml` already has the sheet's ID and the `Stats` tab name. The one
choice to make is `week.ending_weekday` — which weekday the stored row is filed
under (`0` = Monday, `6` = Sunday). Default is Monday. You can change it later;
existing rows keep their old dates.

---

## Usage

```bash
# Normal run: pull the live sheet and store this week.
.venv/bin/python tracker.py

# See what it would store, without writing anything.
.venv/bin/python tracker.py --dry-run

# File this run under a specific date (e.g. you forgot to run it Monday).
.venv/bin/python tracker.py --week-ending 2026-08-24

# Parse a saved grid instead of calling Google (offline / debugging).
.venv/bin/python tracker.py --from-json tests/sample_grid.json --dry-run

# Skip reading the coach's hand-typed "Week ending" log column.
.venv/bin/python tracker.py --no-backfill
```

### Looking at your history

```bash
sqlite3 data/history.db 'SELECT week_ending, weight_avg, steps_avg FROM weekly_summary ORDER BY week_ending;'
```

or just open `data/weekly_summary.csv` in any spreadsheet.

---

## Tests

Offline — they run the parser against `tests/sample_grid.json`, a saved copy of
the real grid. No network or credentials needed.

```bash
.venv/bin/python -m pytest -q
```

---

## Scheduling

The grid is overwritten each week, so the job has to run *after* a week is
complete but *before* you start entering the next one. A **systemd user timer**
in `deploy/` handles this — it fires `tracker.py` every **Monday at 23:00
Pacific** (±15 min): after the coach's Monday feedback, before the grid is
overwritten for the new week. The timezone is pinned in the unit, so it stays
23:00 Pacific regardless of the laptop's system clock. `Persistent=true` means a
missed run (laptop asleep) fires on the next wake.

```bash
./deploy/install.sh          # symlink the units, enable + start the timer
```

| Command | What it does |
|---------|--------------|
| `systemctl --user list-timers nutrition-tracker.timer` | when it next fires |
| `systemctl --user start nutrition-tracker.service`      | run once, right now |
| `journalctl --user -u nutrition-tracker.service -n 20`  | the last run's output |
| `systemctl --user disable --now nutrition-tracker.timer`| stop scheduling |

The units are symlinked from `deploy/`, so editing `nutrition-tracker.timer`
(e.g. to change `OnCalendar`) then running `systemctl --user daemon-reload`
picks up the change. If the machine is usually off/asleep at 07:00 Monday and
you want the job to run even when you're not logged in:
`sudo loginctl enable-linger "$USER"`.

---

## Files

| File                     | Purpose                                             |
|--------------------------|-----------------------------------------------------|
| `tracker.py`             | CLI + all parsing logic                             |
| `db.py`                  | SQLite schema, upserts, CSV export                  |
| `config.toml`            | sheet ID, tab name, week convention, paths          |
| `credentials/`           | the service-account key (git-ignored)               |
| `data/`                  | `history.db` + CSV mirrors (git-ignored)            |
| `tests/`                 | offline parser tests + saved sample grid            |
| `deploy/`                | systemd user timer/service + `install.sh`           |
