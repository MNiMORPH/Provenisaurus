# Provenisaurus — design notes

The design rationale behind Provenisaurus — the decisions that shaped the code and
*why* they were made. The [README](README.md) is the user-facing usage + input
contract; **open work is tracked in GitHub issues** (see "Open work" at the end).
This began as a running handoff and has settled into a design record as the
three-repo pipeline (GravelSource → Provenisaurus → CorraSaurus) matured.

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

**Provenance of the source maps.** Each method's recipe is a one-liner (a slope
threshold, an outcrop union, an `x/max(x)` rescale) already recorded in GRASS
history (`r.info -h`) + git + the study config; the durable assets are the raw
geology / source-area maps / DEM, which are backed up. So GravelSource keeps no
separate "provenance scripts" — capturing those was reviewed (the Toro-prep split)
and judged redundant (A. Wickert).

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
  convention should adjust the map, not the weight — A. Wickert). Float-precision
  noise just past a bound — within `_SOURCE_VALUE_EPS` (`1e-6`), e.g. a
  `1.0000000000001` from an upstream `x/max(x)` rescale — is clamped to the bound
  instead of raising; only an excursion beyond the tolerance counts as malformed
  (issue #2).

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

The workflow ensures the flow network on each run — reuse if all three maps are
present, build (all three together, for consistency) when any is missing or when
`rebuild_basemaps` is set; the region is set to the DEM first. There is no
`build_basemaps` toggle, and `accumulation`/`drainage`/`streams` are not caller
inputs. (The `whole` reuse-path regression is byte-for-byte identical to the
reference — 3,176,159 rows, matching MD5.)

## The channel network (`dist_mode=channel`) — Provenisaurus owns it, the head method is swappable

In `channel` mode the Sternberg attrition acts only along the channel, so the
answer turns on *where the channel begins* — the fluvial channel head ([issue
#1](https://github.com/MNiMORPH/Provenisaurus/issues/1)), one of the biggest levers
on the channel-variant lengths. That head location is set by a `channel_network`
raster (the fluvial domain), against which `site_distance_field` splits the
fluvial-only distance (`dist-to-outlet − dist-to-stream`, clamped ≥ 0).

Like the flow network, Provenisaurus **owns and builds** `channel_network`
(build-or-reuse; rebuilt with the flow network, on which it depends), but the
*criterion* is swappable via `channel_head_method`:

- **`dreich`** (default) — Provenisaurus runs
  [`r.fluvial.channelheads method=dreich`](https://github.com/MNiMORPH/GRASS-fluvial-profiler)
  (DrEICH morphological channel heads; Clubb et al. 2014), which emits the network
  directly as a raster (`raster_network=`). Provenisaurus wires `elevation=dem` and
  **`direction=drainDir`** — its own flow routing — so the network's D8 paths
  coincide with the cells `r.stream.distance` routes along (one routing convention;
  this is what dissolved the original two-authors concern). Tuning options pass
  through verbatim as the `channelheads` mapping (the module validates them).
- **`threshold`** — the fixed `stream_threshold` network (the legacy
  accumulation-threshold proxy). Kept *because* the issue's acceptance includes a
  sensitivity test across head criteria; the proxy is one such criterion.

The head-finding *science* stays in `r.fluvial.channelheads`; Provenisaurus
orchestrates it, owns the resulting map, and stays method-agnostic. The module is
not bundled — a `dreich` run fails early with an install hint if it is absent.

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

## Memory: why the emit path streams and aggregates

A source mask covering most of the map (the all-outcrop bracket) produces ~100 M+
source cells. The original emit held the whole table in memory before writing and
buffered each site's entire `r.stats` dump as a string — which OOM'd the machine. So
the emit path is built to never hold the full table:

- **Streams to disk** — `workflow.run` writes each site's rows as `r.stats` produces
  them (over a `pipe_command`), never accumulating across sites; peak RAM is O(1) in
  the row count.
- **Aggregates at the source** — by default it emits the per-`(site, lith,
  distance-bin)` histogram (`emit.histogram_rows`, `bin_width_m` 12 m), which is
  CorraSaurus's own `reduce_cells` applied upstream: ~540× fewer rows, bit-exact to
  it, so the multi-GB CSV never exists. `bin_width_m: null` falls back to the raw
  per-cell table (byte-for-byte the original output).

Full record — the diagnosis, the bit-exact validation, and the decision trail — is
in [`MEMORY-NOTES.md`](MEMORY-NOTES.md).

## Open work

Tracked in GitHub issues; everything else above is implemented and verified
(history in `git log` and [`MEMORY-NOTES.md`](MEMORY-NOTES.md)).

- **Channel heads** ([issue #1](https://github.com/MNiMORPH/Provenisaurus/issues/1))
  — the machinery is **built** (see "The channel network" above):
  `dist_mode=channel` with `channel_head_method=dreich` orchestrates
  `r.fluvial.channelheads` to build/reuse `channel_network`, routed on the same
  `drainDir`; `threshold` keeps the legacy proxy. Remaining: (a) an **end-to-end
  Toro `channel` run** to verify against real data (needs the GRASS Toro location +
  the `r.fluvial.channelheads` module symlinked in — it is under active development,
  not a packaged addon); (b) the issue-acceptance **sensitivity test** of the
  inverted attrition lengths over the head criterion, a *study*-repo task.
