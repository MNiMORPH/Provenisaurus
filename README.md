# Provenisaurus

Sediment **provenance + transport-distance** extraction for clast-fining /
attrition studies — a *usage of* GRASS GIS, not a new GRASS module.

Given a DEM, a per-class source map (e.g. lithology ∩ a source criterion), and
sample points, it produces — per sample site — the distribution of upstream
**source area vs. downstream transport distance** for each class: the long-format
`source_cells.csv` (`site, lith_index, distance_m, weight`) that
[CorraSaurus](https://github.com/MNiMORPH/CorraSaurus) inverts for attrition
distances.

## It's a workflow, not a module

It orchestrates existing, well-tested GRASS modules — `r.watershed`,
`r.stream.extract`, `r.stream.snap`, `r.stream.distance`, `r.stats` — rather than
implementing a new operation. The whole-path vs. channel-only (fluvial) transport
distance is selectable (`DIST_MODE`).

## Current form

`gis/extract_source_distances.sh` — a documented GRASS shell workflow; run inside
a GRASS session (see the script header for the invocation and the v1 decisions).

## Planned

A cleaned-up **Python workflow** (`grass.script` / pygrass): config-driven, with
the source-mask construction, per-site distance-distribution, and CSV emit as
*testable* functions — same `source_cells.csv` interface, more robust than the
shell prototype.

Extracted from the Quebrada del Toro study via `git filter-repo` (history preserved).
