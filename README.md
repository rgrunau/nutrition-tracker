# nutrition-tracker

Pulls your weekly stats out of the coaching Google Sheet and keeps a permanent
history, so the numbers don't vanish when next week overwrites the grid.

- **Source:** the `Stats` tab of the shared "Robert" sheet.
- **Store:** `data/history.db` (SQLite, the source of truth) + CSV mirrors in
  `data/`, committed to this repo.
- **Runs:** every Monday evening Pacific on GitHub Actions. No computer of
  yours needs to be on.
- **Dashboard:** <https://rgrunau.github.io/nutrition-tracker/>, rebuilt after
  every run.
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
                                        |
              report.py       render data/ into the dashboard page
```

Writes are keyed on the **week-ending date**, so running it repeatedly for the
same week updates that one row instead of piling up duplicates. A manual run on
top of the scheduled one is safe, as long as it happens before the new week's
numbers go into the grid (see [Timing](#timing)).

On GitHub, two workflows chain together:

1. **Weekly archive** (`.github/workflows/weekly.yml`) runs the tests, pulls
   the sheet with `tracker.py`, and commits any changes in `data/` back to
   `main` as `github-actions[bot]`.
2. **Dashboard** (`.github/workflows/pages.yml`) starts when the archive
   finishes, builds the page with `report.py`, and deploys it to GitHub Pages.
   It also rebuilds on any push that touches `report.py`, `db.py` or `data/`.
   It never pulls the sheet.

---

## One-time setup

### 1. Create a Google service account and key

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

   It's git-ignored. Treat it like a password — anyone with this file can read
   anything the service account can read. This repo is public, so the key must
   never be committed.

### 2. Share the sheet with the service account

1. Open `credentials/service-account.json` and copy the `"client_email"` value
   — it looks like `sheet-reader@nutrition-tracker-123456.iam.gserviceaccount.com`.
2. Open the "Robert" sheet in Google Sheets → **Share** → paste that address →
   set it to **Viewer** → untick "Notify people" → *Share*.

Keep the sheet's general access set to **Restricted**. Its ID is in
`config.toml`, which is public, so "anyone with the link" would let anyone read it.

### 3. Give GitHub the key

The workflow reads the key from an encrypted repository secret named
`GOOGLE_SERVICE_ACCOUNT_JSON` and writes it to `credentials/` on the runner.

```bash
gh secret set GOOGLE_SERVICE_ACCOUNT_JSON < credentials/service-account.json
```

Or in the browser: repo → *Settings* → *Secrets and variables* → *Actions* →
*New repository secret*, and paste the whole JSON file. Run the same command
again if you ever rotate the key.

### 4. Turn on GitHub Pages

Repo → *Settings* → *Pages* → *Source*: **GitHub Actions**. (Or
`gh api -X POST repos/rgrunau/nutrition-tracker/pages -f build_type=workflow`.)
On a free GitHub plan, Pages requires the repo to be public.

### 5. Confirm the config

`config.toml` already has the sheet's ID and the `Stats` tab name. The one
choice to make is `week.ending_weekday` — which weekday the stored row is filed
under (`0` = Monday, `6` = Sunday). Default is Monday. You can change it later;
existing rows keep their old dates.

---

## Running on GitHub Actions

### Timing

The grid is overwritten each week, so the job has to run *after* a week is
complete but *before* you start entering the next one. The archive runs every
**Tuesday at 04:23 UTC**, which is **Monday 8:23 PM PST / 9:23 PM PDT**: after the
coach's Monday feedback, before the new week starts.

GitHub's `cron` is UTC only and has no timezone setting, so the Pacific time
shifts by an hour with daylight saving. It's already Tuesday in UTC when the job
runs, so `week_ending_for()` files the run under the Monday that just ended.

GitHub can start scheduled runs late, by hours when it's busy and worst
exactly on the hour. The first run in this repo started almost 10 hours late,
which is why the slot is early in the evening and on an odd minute. To change
it, edit the `cron` line in `.github/workflows/weekly.yml`.

### Common tasks

| Command | What it does |
|---------|--------------|
| `gh run list --limit 5` | recent runs of both workflows, with pass/fail |
| `gh run view <run-id> --log-failed` | the failing step's output (IDs come from `gh run list`) |
| `gh workflow run weekly.yml` | pull the sheet now (same as the *Run workflow* button) |
| `gh workflow run pages.yml` | rebuild the dashboard without pulling the sheet |
| `git pull` | bring the bot's latest `data/` commit down to your laptop |
| `gh workflow disable weekly.yml` | stop the weekly schedule (`enable` to resume) |

A manual archive run mid-week stores the **in-progress** week under the
previous Monday's date, overwriting that week's finished numbers. Run it
manually only on Monday evening, or pass a date with a local run (below).

If a run fails, GitHub emails you. A missed week can be re-run any time before
the grid is overwritten: `gh workflow run weekly.yml`.

---

## Dashboard

<https://rgrunau.github.io/nutrition-tracker/> shows:

- The selected week's weight, steps, sleep and energy, each compared with another week.
- Portion totals against the coach's target ranges (green in range, orange
  out of range; a hollow gray marker shows the comparison week).
- Trend charts for weight, steps, sleep and energy.
- The day-by-day breakdown and a table of every week.

Use the **Week** and **Compare to** dropdowns at the top, or click a week in
the table or a point on a chart. The selected week is kept in the link
(`…/nutrition-tracker/#2026-09-14`), so you can bookmark it. Weeks recovered only
from the coach's log have a weight and nothing else, so they appear on the
weight chart and in the table but not in the dropdowns.

The page is one self-contained HTML file built by `report.py`; to preview a
change locally:

```bash
python3 report.py --out site && xdg-open site/index.html
```

---

## Running locally

Not needed for the weekly job, but handy for backfilling or debugging.

```bash
cd ~/Work/nutrition-tracker
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
git pull                                   # start from the bot's latest data
```

```bash
# Normal run: pull the live sheet and store this week.
.venv/bin/python tracker.py

# See what it would store, without writing anything.
.venv/bin/python tracker.py --dry-run

# File this run under a specific date (e.g. a missed week).
.venv/bin/python tracker.py --week-ending 2026-08-24

# Parse a saved grid instead of calling Google (offline / debugging).
.venv/bin/python tracker.py --from-json tests/sample_grid.json --dry-run

# Skip reading the coach's hand-typed "Week ending" log column.
.venv/bin/python tracker.py --no-backfill
```

A local run changes `data/`. Commit and push it so the next scheduled run
builds on it; otherwise the next `git pull` will conflict with the bot's commit.

If the venv stops working after a system Python upgrade (`No module named
'gspread'`), delete `.venv/` and recreate it with the commands above.

### Looking at your history

```bash
sqlite3 data/history.db 'SELECT week_ending, weight_avg, steps_avg FROM weekly_summary ORDER BY week_ending;'
```

or open `data/weekly_summary.csv` in any spreadsheet, or view it on GitHub,
which renders CSVs as a table.

### Old local timer

`deploy/` holds the systemd user timer that ran this job before GitHub Actions.
It's disabled: it only ran while the laptop was awake. Don't run it alongside
the GitHub schedule, since the two would write diverging histories.
`./deploy/install.sh` turns it back on.

---

## Tests

Offline — they run the parser against `tests/sample_grid.json`, a saved copy of
the real grid. No network or credentials needed. The weekly workflow runs them
before every pull and stops if they fail.

```bash
.venv/bin/python -m pytest -q
```

---

## Files

| File                     | Purpose                                             |
|--------------------------|-----------------------------------------------------|
| `tracker.py`             | CLI + all parsing logic                             |
| `db.py`                  | SQLite schema, upserts, CSV export                  |
| `report.py`              | builds the dashboard page from `data/`              |
| `config.toml`            | sheet ID, tab name, week convention, paths          |
| `credentials/`           | the service-account key (git-ignored)               |
| `data/`                  | `history.db` + CSV mirrors, updated by the bot      |
| `tests/`                 | offline parser tests + saved sample grid            |
| `.github/workflows/`     | `weekly.yml` (archive) and `pages.yml` (dashboard)  |
| `deploy/`                | old systemd user timer, disabled                    |
