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

## Inputs

Provenisaurus runs **inside a GRASS session** and reads existing maps from the
current mapset — *you* supply them (e.g. a study's prep step builds them from raw
data). All maps must share one projected GRASS location / region.

**Required maps**

| input | type | meaning |
|---|---|---|
| `dem` | raster | elevation; sets the analysis region |
| `lithology` | raster | per-cell class code (`lith_index`) — the classes you invert for |
| `source_mask` | raster | `1` where a cell is a clast **source**, else null — *your* source-area definition (lithology ∩ a source criterion: mass-wasting, slope threshold, susceptibility, …) |
| `points` | vector | **raw** sample sites (field coordinates) with a `site` attribute — Provenisaurus snaps them onto the network it builds |
| `drainage`, `streams` | rasters | flow direction + channel network — **supply them, or** set `build_basemaps: true` to build them from the DEM (`r.watershed` + `r.stream.extract` at `stream_threshold`) |
| `accumulation` | raster | flow accumulation — needed for snapping when *not* building base maps (built otherwise) |

The `points` table needs one attribute, `site_column` (default `site`) — the site
name, which becomes the `site` column of the output. **Which** sites to process is
the *caller's* choice: supply only the points you want (e.g. those inside your
study watershed). There is no in-basin filter here — deciding basin membership
needs a study-specific outlet, so it stays with the caller.

**Parameters**
- `source_indices` — which `lith_index` values are modelled sources (others dropped).
- `dist_mode` — `whole` (hillslope + channel) or `channel` (fluvial-only: dist-to-outlet − dist-to-stream).
- `snap_radius` — `r.stream.snap` radius [cells] for snapping raw points onto the network; `null`/`0` if the points are already on it.
- `stream_threshold` — accumulation threshold [cells] for stream extraction (only used if `build_basemaps`).
- `out_csv` — output path.

**Output** — `source_cells.csv` (LF), one row per source cell:
`site, lith_index, distance_m, weight`, i.e. the per-site distribution of source
area (`weight` = cell area) vs. downstream transport distance, for CorraSaurus.

**Assumptions** — `lithology` and `source_mask` are aligned to the DEM grid;
everything is in one projected location. (Points need *not* be pre-snapped —
Provenisaurus snaps them — and there is no in-basin filter; supply the points you
want processed.)

## Usage

```
grass <location>/<mapset> --exec python -m provenisaurus config.yml
```

```yaml
# config.yml
provenisaurus:
  dem: tandemx_toro
  drainage: drainDir
  streams: streams
  lithology: lithology
  source_mask: source_mask
  points: clast_points      # RAW field points (snapped internally)
  site_column: site
  snap_radius: 50           # cells; null -> points already on the network
  source_indices: [2, 3, 4, 5, 6]
  dist_mode: whole          # or: channel
  build_basemaps: false     # true -> build drainage + streams from the DEM
  stream_threshold: 10000   # cells (only if build_basemaps)
  out_csv: source_cells.csv
```

The GRASS-free glue (`provenisaurus.emit`, `provenisaurus.config`) is unit-tested
(`pytest`); the GRASS path is verified by reproducing a known-good extraction.

## Status

The Python workflow (`config` + thin GRASS wrappers + the pure `emit` core) is
done and **regression-verified** to reproduce the original shell extraction
byte-for-byte (3.18M source cells, Quebrada del Toro). The reference shell
prototype `gis/extract_source_distances.sh` is retained for now; the
**Toro-specific input prep** (geology → `lithology`, the source-area mask, snapped
points) lives in the study repo, not here.

Extracted from the Quebrada del Toro study via `git filter-repo` (history preserved).

## License

GPLv3 — see [LICENSE](LICENSE).
