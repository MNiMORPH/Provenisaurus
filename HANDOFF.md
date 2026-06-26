# Provenisaurus — handoff / design notes

Context and decisions for whoever next works on this (including future us). The
[README](README.md) is the user-facing usage + input contract; this file is the
*why* and the *what's-next*.

## Position in the pipeline

```
[raw data: DEM, geology, clast counts]
   → GravelSource   define gravel-producing source areas (multiple methods)  -> source map
   → Provenisaurus  source map → per-site source-area-vs-transport-distance   -> source_cells.csv
   → CorraSaurus    invert clast fining for per-class attrition (e-folding) distances
```

Provenisaurus is the middle box: GIS that turns a **source map + sample points +
a DEM-derived flow network** into the long-format `source_cells.csv`
(`site, lith_index, distance_m, weight`) that CorraSaurus inverts.

## Key decision: Provenisaurus is agnostic about *where gravel comes from*

Defining the source areas is a **separate, plural concern** — there are several
methods (external mass-wasting maps e.g. Tofelde 2018; slope thresholds;
SHALSTAB / physically-based; data-driven susceptibility / PU-learning), and the
choice is one of the *biggest levers* on the final attrition lengths (alongside
channel-head placement). So Provenisaurus deliberately does **not** define source
areas. It takes `source_mask` as a pluggable input.

Those methods live in **GravelSource** — decided (A. Wickert) to be a *folder in
the study / data-input repo*, not a separate repo, where methods can be compared
freely as long as each **exports one simple raster** (the contract below). Spin it
out into its own repo only if a method becomes generally useful. Keep GravelSource
on the *code* side of the data/derived line — it reads raw DEM + geology and
writes a derived map; the raw data stays untouched.

## The source-map contract

The source map is, in effect, a **per-cell production weight**, and Provenisaurus
handles both binary and continuous maps through one path:
`weight = cell_area × source_value`, where `source_value` is the `source_mask`
cell value.

- **Binary.** `source_mask` = `1` where a cell is a source, else null. Then
  `source_value == 1`, so `weight = cell_area` (uniform) — byte-for-byte the
  original behaviour (`144.0` formats to `"144"`), so the regression still holds.
- **Continuous [0,1].** A "clast-generation potential" map → a cell that is "0.3
  likely a source" contributes 0.3× the weight. Values are **enforced to [0,1]**:
  an out-of-range value raises (the map is malformed; callers wanting a different
  convention should adjust the map, not the weight — A. Wickert).

There is no mode flag — binary is just the `source_value == 1` special case.
Implemented in the `Support scalar [0,1] source maps` commit:
`grass_steps.source_cells_stats` dumps a third `r.stats` column (the masked
`source_mask` value); `emit.parse_rstats` yields `(lith_index, distance,
source_value)` and enforces the range; `emit.source_rows` folds the value into the
weight. Everything downstream (CSV schema, CorraSaurus) is unchanged because
`weight` was already the per-cell source weight.

## Border principle (what Provenisaurus owns)

Provenisaurus owns **everything downstream of the DEM that depends on the derived
flow network**: flow routing, stream extraction, snapping sample points onto that
network, per-site watersheds, and distances. The caller supplies only raw data +
study-specific maps + the choice of which points to process:

- supplied: `dem`, `lithology`, `source_mask`, **raw** `points` (+ a `site` column).
- *not* required of the caller: pre-snapped points (Provenisaurus snaps), an
  in-basin filter (the caller just supplies the points it wants — basin membership
  needs a study-specific outlet, so it stays with the caller).

Litmus test: every step needing the flow network is *inside* Provenisaurus; every
input is raw data or a study choice.

## DEM post-processing (the flow network) — Provenisaurus owns it, exclusively

Decided (A. Wickert): Provenisaurus is the *single author* of the DEM-derived flow
network (flow accumulation, drainage direction, streams).

- **No precomputed derivatives accepted as input.** `accumulation`, `drainage`,
  and `streams` are Provenisaurus's own internal maps, not caller inputs. The
  convenience of "pass in maps you already computed" is deliberately *not* offered:
  those derivatives carry conventions the distances depend on (the `r.watershed`
  SFD drainage encoding `r.water.outlet`/`r.stream.distance` expect, the
  accumulation `r.stream.snap` reads, an `r.stream.extract` stream raster), and a
  foreign map built with a different convention (MFD, a different D8 encoding, a
  different stream definition) would pass silently and produce wrong distances.
  One author = no convention to mismatch.
- **Compute once, reuse if present.** If Provenisaurus's own base maps already
  exist in the mapset, reuse them — e.g. a `dist_mode` whole→channel re-run is over
  the *same* network and should cost nothing extra. Since only Provenisaurus writes
  them, the convention is guaranteed. A **force-rebuild** override is needed for
  staleness (the DEM changed): reuse is the default, rebuild is explicit.
- **GravelSource stays decoupled.** Some source-definition methods need the same
  DEM derivatives (slope, accumulation), but GravelSource is a *distinct workflow*
  whose only interface is the [0,1] source raster; if a method needs derivatives it
  computes its own. We accept that duplication to keep the two modules independent.

Status: **implemented.** `build_basemaps` is gone. The workflow ensures the flow
network on each run — reuse if all three maps are present, build (all three
together, for consistency) when any is missing or when `rebuild_basemaps` is set;
the region is set to the DEM first. `accumulation`/`drainage`/`streams` are no
longer caller inputs (config + README updated). Verified: the `whole` reuse-path
regression is still byte-for-byte identical to the reference (3,176,159 rows,
matching MD5).

## Structure

Functional core / imperative shell:
- `emit.py` — **pure, unit-tested** glue: parse `r.stats`, class-filter,
  area-weight, cat→site join, CSV assembly. No GRASS.
- `config.py` — `WorkflowConfig` (validated, YAML).
- `grass_steps.py` — thin `grass.script` wrappers (one per GRASS module).
- `workflow.py` — orchestration + CLI (`grass <loc> --exec python -m provenisaurus config.yml`).

The GRASS path is verified not by unit tests but by **regression**: it reproduces
the original shell extraction's `source_cells.csv` byte-for-byte (3,176,159 rows,
Quebrada del Toro), both for `whole` distances and for the snap-from-raw path.

## Memory: generating a large (all-outcrop) source map — resolved

*History, kept because it explains why the emit path is shaped the way it is.*

**The bug.** The extraction used to hold the **entire output in memory** before
writing, so peak RAM scaled with the *total* row count — fine for the
Tofelde-mapping mask (3.2 M rows), survivable for slope-threshold (39.6 M), but the
all-outcrop mask (~100 M+ rows) OOM'd the machine (a full desktop-session crash).
Three stacked culprits, in order of severity:

1. **Global row accumulator (the dominant one).** `workflow.run` built one `rows`
   list across *all* sites and wrote it in a single `write_source_cells` at the
   end. Every source cell was a live `SourceCell` until then — ~100 M+ objects ≈
   tens of GB; peak scaled with the *whole* CSV, not one site.
2. **Whole-stdout capture, per site.** `source_cells_stats` used
   `gs.read_command("r.stats", …)`, buffering a site's *entire* `r.stats` dump into
   one string, which `parse_rstats` then `splitlines()` into a second full copy —
   several GB for the largest site under all-outcrop, on top of (1).
3. **Root amplifier: `r.stats -1`.** `flags="1n"` prints one line per cell, no
   aggregation — what made the row count explode in the first place.

**The fix — both tiers landed** (see the Status list below):

- **Tier 1 — bound memory, output byte-for-byte unchanged.** `workflow.run` opens
  `out_csv` once and streams each site's rows straight to disk (no cross-site
  accumulator), and `grass_steps.source_cells_stats_stream` reads `r.stats` over a
  `pipe_command` line by line (raising on a non-zero exit, which `read_command`
  used to check) instead of buffering the whole dump. Peak RAM is now O(1) in the
  row count; the Toro `whole` regression stays byte-for-byte identical
  (3,176,159 rows, matching MD5; 694 MB peak RSS).
- **Tier 2 — emit the histogram, so the giant table never exists.** By default the
  workflow emits the per-`(site, lith, distance-bin)` histogram
  (`emit.histogram_rows`, `bin_width_m` default 12 m = a DEM cell) — CorraSaurus's
  `reduce_cells` applied at the source — collapsing one-row-per-cell to
  ~10⁴–10⁵ bins/site (~540× fewer rows; the all-outcrop CSV drops from GBs to a few
  MB). Verified **bit-exact** against `corrasaurus.model.reduce_cells` on the
  39.6 M-row threshold table; `bin_width_m: null` falls back to the raw per-cell
  table (the byte-for-byte path). Because the on-disk artifact is now small, the
  once-proposed CorraSaurus read-side streaming-load fix is moot. See
  `MEMORY-TODO.md` for the distilled record.

## Status / open items

- [x] Python workflow (config + wrappers + pure emit core), regression-verified.
- [x] Snap raw points internally; drop the in-basin filter.
- [x] **Scalar source map** support — `weight = cell_area × source_value`, [0,1]
  enforced, binary unchanged (see "The source-map contract" above). Verified by the
  unit tests *and* the GRASS regression: re-ran the Toro `whole` extraction on the
  post-change code (32 in-basin points, `source_mask` still binary) and the output
  is **byte-for-byte identical** to the pre-change `source_cells.csv` (3,176,159
  rows, matching MD5) — the binary path is provably unaffected.
- [x] **Base-maps ownership** — `accumulation`/`drainage`/`streams` are now
  internal (dropped as caller inputs); the workflow reuses them if present and
  rebuilds all three on `rebuild_basemaps` or when any is missing. `build_basemaps`
  removed. Reuse-path regression still byte-for-byte identical. See "DEM
  post-processing" above. (Config schema change: a config still setting
  `build_basemaps` now errors — downstream Toro configs must drop it.)
- [ ] **Toro-prep split (study side remaining; AW):** the study repo already has
  the per-method `gis/` Provenisaurus configs, and `gis/extract_source_distances.sh`
  has now been **deleted here** — preserved in git history as the provenance
  reference, so nothing is lost. Remaining is study-side: capture the map-build
  provenance (geology→`lithology`; Tofelde→`source_mask`; `src_thr`; KML→**raw**
  `points` + `site`, *no* snap / *no* `in_toro` flag — Provenisaurus snaps, and
  basin membership is the caller's point-selection, so the Campo Quijano outlet +
  watershed stay caller-side) as scripts under `gravelsource/` in
  `toro-clast-attrition`. Provenisaurus keeps every flow-network step.
- [ ] **Channel heads:** `dist_mode=channel` works, but the channel network is a
  fixed area-threshold and the *fluvial* channel head is unresolved — tracked in
  [issue #1](https://github.com/MNiMORPH/Provenisaurus/issues/1) (slope–area /
  Passalacqua-GeoNet / Clubb-DrEICH / field maps; pluggable like `source_mask`).
  Affects only `channel` runs. **Blocked on GRASS-channel-profiler** (the
  channel-head method itself; in progress, AW); the Provenisaurus side is then just
  the pluggable hook — a `channel_heads` map input mirroring `source_mask`.
- [x] **Memory on large source maps (tier 1):** done — stream per-site writes +
  stream `r.stats` stdout (`pipe_command`); peak RAM bounded with byte-for-byte
  output preserved (Toro `whole` regression still matches, 694 MB peak RSS).
- [x] **Extraction-side aggregation (tier 2):** done — `emit.histogram_rows` emits
  the per-`(site, lith, distance-bin)` histogram by default (`bin_width_m`, 12 m),
  CorraSaurus's `reduce_cells` applied at the source: verified bit-exact to it on
  the 39.6 M-row threshold table, ~540× fewer rows. `bin_width_m: null` keeps the
  byte-for-byte per-cell path. The CorraSaurus streaming-load fix is now moot (no
  big CSV to read). See `MEMORY-TODO.md` for the distilled record.
