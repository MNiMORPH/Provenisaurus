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

## The source-map contract (and the one planned change)

The source map is, in effect, a **per-cell production weight**:

- **Binary now.** `source_mask` = `1` where a cell is a source, else null.
  Provenisaurus gates on presence and gives every source cell `weight = cell_area`
  (uniform). This is all the current code does.
- **0–1 scalar later** (A. Wickert's intent). A continuous "clast-generation
  potential" map → `weight = cell_area × potential(cell)`. A cell that is "0.3
  likely a source" contributes 0.3× the weight. This is forward-compatible: the
  contract stays "a per-cell source weight raster," only its *values* change from
  {0,1} to [0,1].

**Where the scalar change goes** (when the scalar map arrives — not yet done):
- `grass_steps.source_cells_stats` currently dumps `(lith_index, distance)` per
  source cell. Add the source value: dump `(lith_index, distance, source_value)`.
- `emit.source_rows` currently sets `weight = cell_area` (constant). Make it
  `weight = cell_area × source_value`.
That's the whole change; everything downstream (CSV schema, CorraSaurus) is
unchanged because `weight` is already the per-cell source weight.

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

## Status / open items

- [x] Python workflow (config + wrappers + pure emit core), regression-verified.
- [x] Snap raw points internally; drop the in-basin filter.
- [ ] **Scalar source map** support (the one change above) — when GravelSource emits a 0–1 map.
- [ ] **Toro-prep split:** the Toro-specific imports (geology→`lithology`, Tofelde→`source_mask`, KML→points) currently live in `gis/extract_source_distances.sh` (retained as reference); move them to the study repo so Provenisaurus carries no Toro specifics, then delete the shell script.
- [ ] **Channel heads:** `dist_mode=channel` is implemented, but the channel network is a fixed area-threshold; the *fluvial* channel head is unresolved (a known open problem — see the study repo). Affects only `channel` runs.
- [ ] Optional: promote `flow_routing`/`extract_streams` etc. into a documented "build base maps" path for studies that want Provenisaurus to build everything.
