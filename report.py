#!/usr/bin/env python3
"""
Build the static dashboard (site/index.html) from the SQLite history.

The page is one self-contained HTML file: the data is embedded as JSON and
rendered in the browser, so there is nothing to serve but the file itself.

Usage:
    python report.py                 # writes site/index.html
    python report.py --out somewhere/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import db
from tracker import load_config


def collect(conn) -> dict:
    """Everything the page needs, as plain JSON-able lists and dicts."""
    weeks = [dict(r) for r in conn.execute(
        "SELECT * FROM weekly_summary ORDER BY week_ending")]
    daily: dict[str, list[dict]] = {}
    for r in conn.execute(
            "SELECT * FROM daily_snapshot ORDER BY week_ending, "
            "CASE day WHEN 'Monday' THEN 1 WHEN 'Tuesday' THEN 2 "
            "WHEN 'Wednesday' THEN 3 WHEN 'Thursday' THEN 4 WHEN 'Friday' THEN 5 "
            "WHEN 'Saturday' THEN 6 ELSE 7 END"):
        daily.setdefault(r["week_ending"], []).append(dict(r))
    targets = {r["label"].lower(): dict(r)
               for r in conn.execute("SELECT * FROM targets")}
    return {"weeks": weeks, "daily": daily, "targets": targets}


def render(data: dict) -> str:
    # "</" can't appear inside a <script> block, so escape it in the JSON.
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", payload)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=str(Path(__file__).with_name("config.toml")))
    p.add_argument("--out", default="site")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    conn = db.connect(cfg["paths"]["database"])
    try:
        data = collect(conn)
    finally:
        conn.close()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(render(data))
    print(f"wrote {out / 'index.html'} ({len(data['weeks'])} weeks)")
    return 0


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nutrition Tracker</title>
<style>
:root {
  --bg: #f7f7f5; --surface: #ffffff; --text: #1d1d1b; --muted: #6b6b66;
  --border: #e4e4df; --accent: #2f6f9f; --accent-soft: #2f6f9f33;
  --good: #2e7d4f; --warn: #b5651d; --faint: #9a9a94;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #161615; --surface: #1f1f1d; --text: #ecece8; --muted: #a3a39c;
    --border: #33332f; --accent: #6fa8d6; --accent-soft: #6fa8d633;
    --good: #6cc28f; --warn: #e0a060; --faint: #6b6b66;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
main { max-width: 960px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 1.5rem; margin: 0 0 4px; }
h2 { font-size: 1.05rem; margin: 0 0 12px; }
.sub { color: var(--muted); margin: 0 0 24px; }
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 16px; margin-bottom: 16px;
}
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
.tile .label { color: var(--muted); font-size: .8rem; text-transform: uppercase; letter-spacing: .04em; }
.tile .value { font-size: 1.6rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.tile .delta { font-size: .85rem; color: var(--muted); }
.portion { display: grid; grid-template-columns: 5.5rem 1fr 6.5rem; gap: 8px; align-items: center; margin: 6px 0; }
.bar { position: relative; height: 10px; background: var(--border); border-radius: 5px; }
.bar .range { position: absolute; top: 0; bottom: 0; background: var(--accent-soft); border-radius: 5px; }
.bar .mark { position: absolute; top: -3px; width: 4px; height: 16px; border-radius: 2px; }
.portion .num { text-align: right; font-variant-numeric: tabular-nums; }
.ok { color: var(--good); } .off { color: var(--warn); }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
.chart-wrap { position: relative; height: 220px; }
.scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-variant-numeric: tabular-nums; }
th, td { padding: 6px 8px; text-align: right; border-bottom: 1px solid var(--border); white-space: nowrap; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--muted); font-weight: 500; font-size: .85rem; }
tr.clickable { cursor: pointer; }
tr.clickable:hover, tr.selected { background: var(--accent-soft); }
.tag { font-size: .75rem; color: var(--faint); }
select { font: inherit; padding: 4px 8px; border-radius: 6px; border: 1px solid var(--border);
         background: var(--surface); color: var(--text); }
.row { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
.row h2 { margin: 0; }
.empty { color: var(--muted); }
.controls { display: flex; flex-wrap: wrap; gap: 12px 20px; margin-bottom: 16px; }
.controls label { display: flex; flex-direction: column; gap: 4px; color: var(--muted); font-size: .8rem;
                  text-transform: uppercase; letter-spacing: .04em; min-width: 0; }
.controls select { font-size: 1rem; text-transform: none; letter-spacing: normal; padding: 8px 10px; max-width: 100%; }
select:focus-visible, tr.clickable:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.bar .mark.cmp { background: var(--surface); border: 2px solid var(--muted); width: 6px; }
.legend { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: .85rem; }
.legend .key { display: inline-block; width: 4px; height: 14px; border-radius: 2px; background: var(--text); }
.legend .key-cmp { width: 6px; background: var(--surface); border: 2px solid var(--muted); margin-left: 10px; }
tr.compared { box-shadow: inset 3px 0 0 var(--muted); }
.charts canvas { cursor: pointer; }
</style>
</head>
<body>
<main>
  <h1>Nutrition Tracker</h1>
  <p class="sub" id="sub"></p>

  <section class="controls">
    <label for="week-pick">Week
      <select id="week-pick"></select>
    </label>
    <label for="compare-pick">Compare to
      <select id="compare-pick"></select>
    </label>
  </section>

  <section class="card">
    <h2 id="week-title">Week</h2>
    <div class="tiles" id="tiles"></div>
  </section>

  <section class="card">
    <div class="row">
      <h2>Portions vs. target <span class="tag">weekly totals</span></h2>
      <div class="legend" id="portion-legend"></div>
    </div>
    <div id="portions"></div>
  </section>

  <section class="charts">
    <div class="card"><h2>Weight <span class="tag">weekly avg</span></h2><div class="chart-wrap"><canvas id="c-weight"></canvas></div></div>
    <div class="card"><h2>Steps <span class="tag">daily avg</span></h2><div class="chart-wrap"><canvas id="c-steps"></canvas></div></div>
    <div class="card"><h2>Sleep <span class="tag">hours, avg</span></h2><div class="chart-wrap"><canvas id="c-sleep"></canvas></div></div>
    <div class="card"><h2>Energy <span class="tag">1–5, avg</span></h2><div class="chart-wrap"><canvas id="c-energy"></canvas></div></div>
  </section>

  <section class="card">
    <h2 id="daily-title">Daily breakdown</h2>
    <div class="scroll"><table id="daily"></table></div>
  </section>

  <section class="card">
    <h2>All weeks <span class="tag">click a week to select it</span></h2>
    <div class="scroll"><table id="weeks"></table></div>
  </section>
</main>

<script id="data" type="application/json">__DATA__</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
const weeks = DATA.weeks;
// Only weeks pulled from the sheet have the full set of numbers; weeks from
// the coach's log carry a weight and nothing else, so they can't be selected.
const full = weeks.filter(w => w.source === "sheet");
const byDate = Object.fromEntries(full.map(w => [w.week_ending, w]));
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

const fmt = (v, d = 1) => v == null ? "—" : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const hrs = v => v == null ? "—" : `${Math.floor(v)}h ${String(Math.round((v % 1) * 60)).padStart(2, "0")}m`;
const dateLabel = iso => new Date(iso + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
const short = iso => new Date(iso + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
const el = (tag, attrs = {}, text) => { const e = Object.assign(document.createElement(tag), attrs); if (text != null) e.textContent = text; return e; };

document.getElementById("sub").textContent = weeks.length
  ? `${weeks.length} weeks on record, ${dateLabel(weeks[0].week_ending)} – ${dateLabel(weeks[weeks.length - 1].week_ending)}. Updated every Monday night.`
  : "No data yet.";

// ---- dropdowns --------------------------------------------------------------
const weekPick = document.getElementById("week-pick");
const comparePick = document.getElementById("compare-pick");
const newestFirst = [...full].reverse();
for (const w of newestFirst) weekPick.append(el("option", { value: w.week_ending }, `Week ending ${dateLabel(w.week_ending)}`));

const PRIOR = "prior", NONE = "none";
const state = { week: newestFirst[0]?.week_ending, compare: PRIOR };

function priorOf(we) {
  const i = full.findIndex(w => w.week_ending === we);
  return i > 0 ? full[i - 1] : null;
}
function compareWeek() {
  if (state.compare === NONE) return null;
  if (state.compare === PRIOR) return priorOf(state.week);
  return byDate[state.compare] || null;
}
function fillCompare() {
  const prior = priorOf(state.week);
  comparePick.replaceChildren(
    el("option", { value: PRIOR }, prior ? `Week before (${short(prior.week_ending)})` : "Week before (none)"),
    el("option", { value: NONE }, "Nothing"),
    ...newestFirst.filter(w => w.week_ending !== state.week)
      .map(w => el("option", { value: w.week_ending }, `Week ending ${dateLabel(w.week_ending)}`)));
  if (state.compare === state.week) state.compare = PRIOR;
  comparePick.value = state.compare;
}

weekPick.addEventListener("change", () => select(weekPick.value));
comparePick.addEventListener("change", () => { state.compare = comparePick.value; render(); });

// The selected week rides in the link (#2026-10-05) so it can be bookmarked.
function select(we) {
  if (!byDate[we]) return;
  state.week = we;
  try { if (location.hash.slice(1) !== we) history.replaceState(null, "", "#" + we); } catch {}
  render();
}
window.addEventListener("hashchange", () => select(location.hash.slice(1)));

// ---- tiles ----------------------------------------------------------------
function renderTiles(cur, cmp) {
  document.getElementById("week-title").textContent = `Week ending ${dateLabel(cur.week_ending)}`;
  const tiles = [
    ["Weight", "weight_avg", v => fmt(v, 1), " lb"],
    ["Steps", "steps_avg", v => fmt(v, 0), ""],
    ["Sleep", "sleep_avg", hrs, null],
    ["Energy", "energy_avg", v => fmt(v, 1), ""],
  ];
  const box = document.getElementById("tiles");
  box.replaceChildren();
  for (const [label, key, f, unit] of tiles) {
    const v = cur[key], p = cmp?.[key];
    const t = el("div", { className: "tile" });
    t.append(el("div", { className: "label" }, label), el("div", { className: "value" }, f(v) + (unit && v != null ? unit : "")));
    if (cmp && v != null && p != null) {
      const d = v - p;
      const sign = d > 0 ? "+" : d < 0 ? "−" : "±";
      const shown = key === "sleep_avg" ? `${Math.round(Math.abs(d) * 60)}m` : fmt(Math.abs(d), key === "steps_avg" ? 0 : 1);
      t.append(el("div", { className: "delta" }, `${sign}${shown} vs. ${short(cmp.week_ending)}`));
    } else if (cmp) {
      t.append(el("div", { className: "delta" }, `no ${label.toLowerCase()} for ${short(cmp.week_ending)}`));
    }
    box.append(t);
  }
}

// ---- portions vs target ---------------------------------------------------
function renderPortions(cur, cmp) {
  const legend = document.getElementById("portion-legend");
  legend.replaceChildren(el("span", { className: "key key-cur" }), ` ${short(cur.week_ending)}`);
  if (cmp) legend.append(el("span", { className: "key key-cmp" }), ` ${short(cmp.week_ending)}`);

  const box = document.getElementById("portions");
  box.replaceChildren();
  for (const key of ["protein", "carb", "fat", "veggies"]) {
    const t = DATA.targets[key] || {};
    const v = cur[key + "_total"], c = cmp?.[key + "_total"];
    const lo = t.low, hi = t.high;
    const max = Math.max(v || 0, c || 0, hi || lo || 0) * 1.15 || 1;
    const inRange = v != null && (lo == null || v >= lo) && (hi == null || v <= hi);
    const row = el("div", { className: "portion" });
    row.append(el("div", {}, key[0].toUpperCase() + key.slice(1)));
    const bar = el("div", { className: "bar" });
    if (lo != null) {
      const r = el("div", { className: "range" });
      r.style.left = `${(lo / max) * 100}%`;
      r.style.width = `${(((hi ?? max) - lo) / max) * 100}%`;
      bar.append(r);
    }
    if (c != null) {
      const m = el("div", { className: "mark cmp", title: `${short(cmp.week_ending)}: ${fmt(c, 1)}` });
      m.style.left = `calc(${(c / max) * 100}% - 2px)`;
      bar.append(m);
    }
    if (v != null) {
      const m = el("div", { className: "mark", title: `${short(cur.week_ending)}: ${fmt(v, 1)}` });
      m.style.left = `calc(${(v / max) * 100}% - 2px)`;
      m.style.background = inRange ? css("--good") : css("--warn");
      bar.append(m);
    }
    row.append(bar);
    const range = lo == null ? "" : hi == null ? ` / ${fmt(lo, 0)}+` : ` / ${fmt(lo, 0)}–${fmt(hi, 0)}`;
    row.append(el("div", { className: "num " + (inRange ? "ok" : "off") }, fmt(v, 1) + range));
    box.append(row);
  }
}

// ---- charts ---------------------------------------------------------------
// Built once; render() only restyles the points for the selected weeks.
const charts = [];
if (window.Chart) {
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--border");
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  const base = (yTitle, y = {}) => ({
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: { y: { title: { display: !!yTitle, text: yTitle }, ...y }, x: { grid: { display: false } } },
    onClick: (_e, els, chart) => {
      const w = els.length && chart.$rows[els[0].index];
      if (w && byDate[w.week_ending]) select(w.week_ending);
    },
  });

  const make = (id, rows, field, type, opts) => {
    const chart = new Chart(document.getElementById(id), {
      type, data: { labels: rows.map(w => short(w.week_ending)),
                    datasets: [{ data: rows.map(w => w[field]), tension: .25, spanGaps: true,
                                 borderWidth: type === "bar" ? 1 : 2 }] },
      options: opts,
    });
    chart.$rows = rows;
    charts.push(chart);
  };

  // Weight uses every week, including weights recovered from the coach's log.
  const weightOpts = base("lb");
  weightOpts.plugins.tooltip = { callbacks: {
    afterLabel: c => weeks[c.dataIndex].source === "backfill" ? "(from coach's log)" : "" } };
  make("c-weight", weeks, "weight_avg", "line", weightOpts);
  make("c-steps", full, "steps_avg", "bar", base("", { beginAtZero: true }));
  make("c-sleep", full, "sleep_avg", "line", base("hours"));
  make("c-energy", full, "energy_avg", "line", base("", { min: 1, max: 5 }));
}

function renderCharts(cur, cmp) {
  const accent = css("--accent"), soft = css("--accent-soft"), muted = css("--faint");
  for (const chart of charts) {
    const ds = chart.data.datasets[0];
    const role = chart.$rows.map(w => w.week_ending === cur.week_ending ? "cur"
                                   : cmp && w.week_ending === cmp.week_ending ? "cmp" : "");
    if (chart.config.type === "bar") {
      ds.backgroundColor = role.map(r => r === "cur" ? accent : r === "cmp" ? muted : soft);
      ds.borderColor = role.map(r => r === "cmp" ? muted : accent);
    } else {
      ds.borderColor = accent;
      ds.backgroundColor = role.map(r => r === "cur" ? accent : r === "cmp" ? muted : css("--surface"));
      ds.pointBorderColor = role.map(r => r === "cmp" ? muted : accent);
      ds.pointRadius = role.map((r, i) => r ? 6 : chart.$rows[i].source === "sheet" ? 3 : 2.5);
      ds.pointStyle = chart.$rows.map(w => w.source === "sheet" ? "circle" : "rectRot");
    }
    chart.update("none");
  }
}

// ---- daily breakdown --------------------------------------------------------
function renderDaily(cur) {
  document.getElementById("daily-title").textContent = `Daily breakdown, week ending ${dateLabel(cur.week_ending)}`;
  const t = document.getElementById("daily");
  t.replaceChildren();
  const rows = DATA.daily[cur.week_ending] || [];
  if (!rows.length) { t.append(el("caption", { className: "empty" }, "No daily data for this week.")); return; }
  const cols = [["Day", r => r.day], ["Protein", r => fmt(r.protein, 1)], ["Carb", r => fmt(r.carb, 1)],
                ["Fat", r => fmt(r.fat, 1)], ["Veggies", r => fmt(r.veggies, 1)], ["Sleep", r => hrs(r.sleep)],
                ["Energy", r => fmt(r.energy, 0)], ["Weight", r => fmt(r.weight, 1)], ["Steps", r => fmt(r.steps, 0)],
                ["Training", r => r.training || ""]];
  const head = el("tr");
  cols.forEach(([h]) => { const th = el("th", {}, h); if (h === "Training") th.style.textAlign = "left"; head.append(th); });
  t.append(head);
  for (const r of rows) {
    const tr = el("tr");
    cols.forEach(([h, f]) => { const td = el("td", {}, f(r)); if (h === "Training") td.style.textAlign = "left"; tr.append(td); });
    t.append(tr);
  }
}

// ---- all weeks table --------------------------------------------------------
(() => {
  const t = document.getElementById("weeks");
  const cols = ["Week ending", "Weight", "Steps", "Protein", "Carb", "Fat", "Veggies", "Sleep", "Energy"];
  const head = el("tr");
  cols.forEach(h => head.append(el("th", {}, h)));
  t.append(head);
  for (const w of [...weeks].reverse()) {
    const tr = el("tr");
    tr.dataset.we = w.week_ending;
    const first = el("td", {}, dateLabel(w.week_ending));
    if (w.source === "backfill") first.append(" ", el("span", { className: "tag" }, "coach's log"));
    tr.append(first);
    [fmt(w.weight_avg, 1), fmt(w.steps_avg, 0), fmt(w.protein_total, 1), fmt(w.carb_total, 1),
     fmt(w.fat_total, 1), fmt(w.veggies_total, 1), hrs(w.sleep_avg), fmt(w.energy_avg, 1)]
      .forEach(v => tr.append(el("td", {}, v)));
    if (byDate[w.week_ending]) {
      tr.className = "clickable";
      tr.tabIndex = 0;
      const go = () => { select(w.week_ending); weekPick.scrollIntoView({ behavior: "smooth", block: "center" }); };
      tr.addEventListener("click", go);
      tr.addEventListener("keydown", e => { if (e.key === "Enter") go(); });
    }
    t.append(tr);
  }
})();

// ---- wire it together -------------------------------------------------------
function render() {
  const cur = byDate[state.week];
  if (!cur) return;
  weekPick.value = state.week;
  fillCompare();
  const cmp = compareWeek();
  renderTiles(cur, cmp);
  renderPortions(cur, cmp);
  renderCharts(cur, cmp);
  renderDaily(cur);
  document.querySelectorAll("#weeks tr").forEach(tr => {
    tr.classList.toggle("selected", tr.dataset.we === state.week);
    tr.classList.toggle("compared", !!cmp && tr.dataset.we === cmp.week_ending);
  });
}

if (full.length) {
  if (byDate[location.hash.slice(1)]) state.week = location.hash.slice(1);
  render();
} else {
  document.getElementById("tiles").append(el("p", { className: "empty" }, "No full weeks yet."));
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
