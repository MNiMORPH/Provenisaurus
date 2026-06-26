# What we actually have to do: memory for large source maps

Distilled from the CorraSaurus-side companion note (now deleted — its job done) and
the **"Memory: generating a large (all-outcrop) source map"** section of
[`HANDOFF.md`](HANDOFF.md), which holds the full diagnosis. This file is the live
action list; `HANDOFF.md` is the *why*.

## The problem, in one line

The extraction used to hold the **entire** source-cells table in RAM before writing
(global `rows` accumulator + whole-stdout `read_command` + `r.stats -1`), so peak
memory scaled with the *total* row count: fine for the Tofelde mask (3.2 M rows),
survivable for slope-threshold (39.6 M), but the all-outcrop mask (~100 M+ rows)
OOM'd the whole desktop session.

**Sizing (kept from the companion note's §2, so it isn't lost):** 39.6 M is the
*nested sum* over the 32 nested sites, not a per-site count — each source cell is
emitted once per downstream site. The largest single (outlet) site emits the
distinct basin cell count `N ≈ 5–10 M` for threshold, so **~13–25 M ≈ 2–4 GB for
all-outcrop at the peak site**. Whole-table peak for outcrop was therefore
**~15–22 GB**; bounding it to one streamed site is what made the run survivable.

## Done — Tier 1: bound memory, output byte-for-byte unchanged ✅

Streaming write-side, implemented **and verified this session**. Four edits, all in
the Provenisaurus package (none in CorraSaurus):

1. `emit.py` — line-based core (`parse_rstats_lines`, `iter_source_rows`); the
   string `parse_rstats` / `source_rows` kept as thin wrappers (unit tests untouched).
2. `emit.py` — `open_source_cells` incremental writer (header once, append per row);
   `write_source_cells` reimplemented as a wrapper over it.
3. `grass_steps.py` — `source_cells_stats_stream` streams `r.stats` via
   `pipe_command` instead of `read_command`'s full buffer; `wait()` + raise
   `CalledModuleError` on non-zero return (`pipe_command` does **not** error-check,
   so a mid-stream failure would otherwise pass silently as a truncated CSV).
4. `workflow.py` — open the writer once, stream each site's rows straight to disk,
   drop the `rows = []` / `rows.extend(...)` accumulation.

Because the workflow streams the **generator** (`iter_source_rows`) rather than the
list (`source_rows`), peak is **O(1) within a site too** — the note's deferred
"Tier 1.5" achieved for free, while `source_rows` stays a list so
`test_source_rows_empty_when_no_sources` still holds. (Both halves matter: (a)
per-site streaming removes the dominant cross-site accumulator; (b) `r.stats`
stdout streaming removes the secondary per-site string + its `splitlines()` copy.)

**Verified:**
- 14/14 `test_emit.py` unit tests pass; ruff clean.
- 50 M-row synthetic stream: **0.17 MB** Python heap (vs ~5.7 GB if accumulated).
- Toro `whole` regression: **byte-for-byte identical** — 3,176,159 rows, MD5
  `a5241ceb5bf1d52fb01fda98e2aef865`, peak RSS **694 MB** (mostly GRASS itself).

Committed in `Stream source cells to disk instead of accumulating in memory`.

## Done — Tier 2: emit the histogram, never the per-cell table ✅

Provenisaurus now writes the **per-`(site, lith_index, distance-bin)` histogram**
directly (`bin_width_m`, default **12 m** = a DEM cell), summed weight at the
weight-mean distance — this is **CorraSaurus's own `reduce_cells`, applied at the
source**, so the inversion input is unchanged but the on-disk CSV shrinks ~10²–10³×.
`bin_width_m: null` still emits the raw per-cell table (the byte-for-byte path).

- `emit.histogram_rows` fuses the reduction into the per-site streaming pass
  (holds one site's bins, O(#bins)).
- **Validated** against `corrasaurus.model.reduce_cells` on the real 39.6 M-row
  threshold table: **bit-exact** (same 73,304 bins, `max|ΔW|=0`, `max|Δdist|=0`);
  end-to-end fractions match to `< 3e-7` for the raw, 12 m, and 100 m consumers.
  **540× fewer rows** (~1 GB → ~2 MB; the all-outcrop table → a few MB).
- This removes the multi-GB CSV entirely, so the **all-outcrop bracket can now be
  generated** without the write OOM (Tier 1) *or* a giant artifact (Tier 2).
- Handoff left for CorraSaurus (`CorraSaurus/HANDOFF-Provenisaurus.md`): no changes
  needed there; `reduce_cells` stays (idempotent on the pre-reduced data, still used
  to coarsen to 100 m for MCMC speed). One coupling: `histogram_rows` *reimplements*
  the binning, so the two must stay in sync.

## Not needed — CorraSaurus read-side streaming load

A chunked fused-reduce in `corrasaurus/io.py` would bound RAM while *reading* the big
CSV back. Moot now: Tier 2 shrinks the file at the source, so there is no big CSV to
read. Only revisit if a raw per-cell table (`bin_width_m: null`) is ever fed to the
inversion at scale.

## Status

Tier 1 (streaming write) and Tier 2 (histogram emit) both **done and verified**. The
all-outcrop bracket is unblocked end to end.
