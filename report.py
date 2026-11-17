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
</style>
</head>
<body>
<main>
  <h1>Nutrition Tracker</h1>
  <p class="sub" id="sub"></p>

  <section class="card">
    <h2 id="latest-title">Latest week</h2>
    <div class="tiles" id="tiles"></div>
  </section>

  <section class="card">
    <h2>Portions vs. target <span class="tag">weekly totals</span></h2>
    <div id="portions"></div>
  </section>

  <section class="charts">
    <div class="card"><h2>Weight <span class="tag">weekly avg</span></h2><div class="chart-wrap"><canvas id="c-weight"></canvas></div></div>
    <div class="card"><h2>Steps <span class="tag">daily avg</span></h2><div class="chart-wrap"><canvas id="c-steps"></canvas></div></div>
    <div class="card"><h2>Sleep <span class="tag">hours, avg</span></h2><div class="chart-wrap"><canvas id="c-sleep"></canvas></div></div>
    <div class="card"><h2>Energy <span class="tag">1–5, avg</span></h2><div class="chart-wrap"><canvas id="c-energy"></canvas></div></div>
  </section>

  <section class="card">
    <div class="row">
      <h2>Daily breakdown</h2>
      <select id="week-pick" aria-label="Week"></select>
    </div>
    <div class="scroll"><table id="daily"></table></div>
  </section>

  <section class="card">
    <h2>All weeks</h2>
    <div class="scroll"><table id="weeks"></table></div>
  </section>
</main>

<script id="data" type="application/json">__DATA__</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>
const DATA = JSON.parse(document.getElementById("data").textContent);
const weeks = DATA.weeks;
const full = weeks.filter(w => w.source === "sheet");
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

const fmt = (v, d = 1) => v == null ? "—" : Number(v).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const hrs = v => v == null ? "—" : `${Math.floor(v)}h ${String(Math.round((v % 1) * 60)).padStart(2, "0")}m`;
const dateLabel = iso => new Date(iso + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
const short = iso => new Date(iso + "T12:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" });
const el = (tag, attrs = {}, text) => { const e = Object.assign(document.createElement(tag), attrs); if (text != null) e.textContent = text; return e; };

const latest = full[full.length - 1];
const prev = full[full.length - 2];
document.getElementById("sub").textContent = weeks.length
  ? `${weeks.length} weeks on record, ${dateLabel(weeks[0].week_ending)} – ${dateLabel(weeks[weeks.length - 1].week_ending)}. Updated every Monday night.`
  : "No data yet.";

// ---- latest week tiles ---------------------------------------------------
if (latest) {
  document.getElementById("latest-title").textContent = `Week ending ${dateLabel(latest.week_ending)}`;
  const tiles = [
    ["Weight", latest.weight_avg, prev?.weight_avg, v => fmt(v, 1), " lb"],
    ["Steps", latest.steps_avg, prev?.steps_avg, v => fmt(v, 0), ""],
    ["Sleep", latest.sleep_avg, prev?.sleep_avg, hrs, null],
    ["Energy", latest.energy_avg, prev?.energy_avg, v => fmt(v, 1), ""],
  ];
  const box = document.getElementById("tiles");
  for (const [label, v, p, f, unit] of tiles) {
    const t = el("div", { className: "tile" });
    t.append(el("div", { className: "label" }, label), el("div", { className: "value" }, f(v) + (unit && v != null ? unit : "")));
    if (v != null && p != null) {
      const d = v - p;
      const sign = d > 0 ? "+" : d < 0 ? "−" : "±";
      const shown = label === "Sleep" ? `${Math.round(Math.abs(d) * 60)}m` : fmt(Math.abs(d), label === "Steps" ? 0 : 1);
      t.append(el("div", { className: "delta" }, `${sign}${shown} vs. prior week`));
    }
    box.append(t);
  }
}

// ---- portions vs target --------------------------------------------------
(() => {
  const box = document.getElementById("portions");
  if (!latest) { box.append(el("p", { className: "empty" }, "No full weeks yet.")); return; }
  for (const key of ["protein", "carb", "fat", "veggies"]) {
    const t = DATA.targets[key] || {};
    const v = latest[key + "_total"];
    const lo = t.low, hi = t.high;
    const max = Math.max(v || 0, hi || lo || 0) * 1.15 || 1;
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
    if (v != null) {
      const m = el("div", { className: "mark" });
      m.style.left = `calc(${(v / max) * 100}% - 2px)`;
      m.style.background = inRange ? css("--good") : css("--warn");
      bar.append(m);
    }
    row.append(bar);
    const range = lo == null ? "" : hi == null ? ` / ${fmt(lo, 0)}+` : ` / ${fmt(lo, 0)}–${fmt(hi, 0)}`;
    row.append(el("div", { className: "num " + (inRange ? "ok" : "off") }, fmt(v, 1) + range));
    box.append(row);
  }
})();

// ---- charts ---------------------------------------------------------------
if (window.Chart) {
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--border");
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  const base = (yTitle) => ({
    responsive: true, maintainAspectRatio: false,
    plugins: { legend: { display: false } },
    scales: { y: { title: { display: !!yTitle, text: yTitle } }, x: { grid: { display: false } } },
  });
  const accent = css("--accent");

  // Weight uses every week, including weights recovered from the coach's log.
  new Chart(document.getElementById("c-weight"), {
    type: "line",
    data: {
      labels: weeks.map(w => short(w.week_ending)),
      datasets: [{
        data: weeks.map(w => w.weight_avg), borderColor: accent, backgroundColor: accent,
        pointRadius: weeks.map(w => w.source === "sheet" ? 4 : 3),
        pointStyle: weeks.map(w => w.source === "sheet" ? "circle" : "rectRot"),
        tension: .25, spanGaps: true,
      }],
    },
    options: { ...base("lb"), plugins: { legend: { display: false }, tooltip: {
      callbacks: { afterLabel: c => weeks[c.dataIndex].source === "backfill" ? "(from coach's log)" : "" } } } },
  });

  const line = (id, field, yTitle, opts = {}) => new Chart(document.getElementById(id), {
    type: opts.type || "line",
    data: { labels: full.map(w => short(w.week_ending)),
            datasets: [{ data: full.map(w => w[field]), borderColor: accent,
                         backgroundColor: opts.type === "bar" ? css("--accent-soft") : accent,
                         borderWidth: opts.type === "bar" ? 1 : 2, tension: .25 }] },
    options: { ...base(yTitle), scales: { ...base(yTitle).scales, y: { ...base(yTitle).scales.y, ...opts.y } } },
  });
  line("c-steps", "steps_avg", "", { type: "bar", y: { beginAtZero: true } });
  line("c-sleep", "sleep_avg", "hours");
  line("c-energy", "energy_avg", "", { y: { min: 1, max: 5 } });
}

// ---- daily breakdown ------------------------------------------------------
const pick = document.getElementById("week-pick");
const withDaily = Object.keys(DATA.daily).sort().reverse();
for (const we of withDaily) pick.append(el("option", { value: we }, `Week ending ${dateLabel(we)}`));

function showDaily(we) {
  const t = document.getElementById("daily");
  t.replaceChildren();
  const rows = DATA.daily[we] || [];
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
  pick.value = we;
  document.querySelectorAll("#weeks tr.clickable").forEach(tr => tr.classList.toggle("selected", tr.dataset.we === we));
}
pick.addEventListener("change", () => showDaily(pick.value));

// ---- all weeks table --------------------------------------------------------
(() => {
  const t = document.getElementById("weeks");
  const cols = ["Week ending", "Weight", "Steps", "Protein", "Carb", "Fat", "Veggies", "Sleep", "Energy"];
  const head = el("tr");
  cols.forEach(h => head.append(el("th", {}, h)));
  t.append(head);
  for (const w of [...weeks].reverse()) {
    const tr = el("tr");
    const first = el("td", {}, dateLabel(w.week_ending));
    if (w.source === "backfill") first.append(" ", el("span", { className: "tag" }, "coach's log"));
    tr.append(first);
    [fmt(w.weight_avg, 1), fmt(w.steps_avg, 0), fmt(w.protein_total, 1), fmt(w.carb_total, 1),
     fmt(w.fat_total, 1), fmt(w.veggies_total, 1), hrs(w.sleep_avg), fmt(w.energy_avg, 1)]
      .forEach(v => tr.append(el("td", {}, v)));
    if (DATA.daily[w.week_ending]) {
      tr.className = "clickable";
      tr.dataset.we = w.week_ending;
      tr.addEventListener("click", () => { showDaily(w.week_ending); pick.scrollIntoView({ behavior: "smooth", block: "center" }); });
    }
    t.append(tr);
  }
})();

if (withDaily.length) showDaily(withDaily[0]);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
