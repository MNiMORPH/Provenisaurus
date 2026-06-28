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
current mapset — *you* supply the inputs below (e.g. a study's prep step builds
them from raw data); Provenisaurus builds the flow network it needs. All maps must
share one projected GRASS location / region.

**Required maps**

| input | type | meaning |
|---|---|---|
| `dem` | raster | elevation; sets the analysis region |
| `lithology` | raster | per-cell class code (`lith_index`) — the classes you invert for |
| `source_mask` | raster | per-cell clast-**source** production weight, else null — `1` where a cell is a source (binary), or a continuous `[0,1]` "production potential"; *your* source-area definition (lithology ∩ a source criterion: mass-wasting, slope threshold, susceptibility, …) |
| `points` | vector | **raw** sample sites (field coordinates) with a `site` attribute — Provenisaurus snaps them onto the network it builds |

**Flow network (built for you, not an input).** Provenisaurus owns the DEM-derived
flow network — flow accumulation, drainage direction, and the stream network. It
builds them from the `dem` (`r.watershed` + `r.stream.extract` at
`stream_threshold`) when they're absent, **reuses** them if they already exist in
the mapset (so a `dist_mode` re-run over the same DEM costs nothing extra), and
rebuilds them only when you set `rebuild_basemaps: true`. You do **not** supply
them: there is one author of the flow network, so there is no foreign convention to
mismatch.

The `points` table needs one attribute, `site_column` (default `site`) — the site
name, which becomes the `site` column of the output. **Which** sites to process is
the *caller's* choice: supply only the points you want (e.g. those inside your
study watershed). There is no in-basin filter here — deciding basin membership
needs a study-specific outlet, so it stays with the caller.

**Parameters**
- `source_indices` — which `lith_index` values are modelled sources (others dropped).
- `dist_mode` — `whole` (hillslope + channel) or `channel` (fluvial-only: dist-to-outlet − dist-to-stream, split against the channel network).
- `channel_network` — raster naming the fluvial channel cells, used in `channel` mode to set where the channel begins (the channel head). A pluggable study input, like `source_mask`: Provenisaurus stays agnostic about *where channels begin* and consumes a network you supply — built by [`r.fluvial.channelheads`](https://github.com/MNiMORPH/GRASS-fluvial-profiler) (recommended `method=lsdtt`, DrEICH morphological channel heads), which authors the channel network and its structure. `null` (default) falls back to the internally-extracted `stream_threshold` network — the legacy fixed-accumulation-threshold proxy for the channel head ([issue #1](https://github.com/MNiMORPH/Provenisaurus/issues/1)). Ignored in `whole` mode.
- `snap_radius` — `r.stream.snap` radius [cells] for snapping raw points onto the network; `null`/`0` if the points are already on it.
- `stream_threshold` — accumulation threshold [cells] for stream extraction (used when the flow network is built/rebuilt).
- `rebuild_basemaps` — force-rebuild the flow network even if it already exists (default: reuse if present).
- `bin_width_m` — distance-bin width [m] for the emitted histogram (default `12` = a DEM cell); `null` emits the raw one-row-per-cell table.
- `out_csv` — output path.

**Output** — `source_cells.csv` (LF): `site, lith_index, distance_m, weight`, the
per-site distribution of source production (`weight` = cell area × the cell's source
potential — just cell area for a binary mask) vs. downstream transport distance, for
CorraSaurus. By default the rows are a **per-`(site, lith_index, distance-bin)`
histogram** (`bin_width_m`, default 12 m = a DEM cell): cells in a bin are collapsed
to their summed `weight` at the weight-mean `distance_m`. This is CorraSaurus's own
`reduce_cells` reduction applied at the source — algebraically the same input to the
inversion (verified bit-exact), but ~10²–10³× fewer rows, so a source mask covering
most of the map stays a few MB instead of multiple GB. `bin_width_m: null` instead
emits the raw one-row-per-source-cell table (the byte-for-byte regression path).

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
  lithology: lithology
  source_mask: source_mask
  points: clast_points      # RAW field points (snapped internally)
  site_column: site
  snap_radius: 50           # cells; null -> points already on the network
  source_indices: [2, 3, 4, 5, 6]
  dist_mode: whole          # or: channel
  channel_network: null     # channel mode: fluvial network (r.fluvial.channelheads); null -> stream_threshold proxy
  stream_threshold: 10000   # cells; for building the stream network
  rebuild_basemaps: false   # true -> rebuild the flow network even if present
  bin_width_m: 12           # distance-bin width [m]; null -> raw one row per cell
  out_csv: source_cells.csv
```

The GRASS-free glue (`provenisaurus.emit`, `provenisaurus.config`) is unit-tested
(`pytest`); the GRASS path is verified by reproducing a known-good extraction.

## Status

The Python workflow (`config` + thin GRASS wrappers + the pure `emit` core) is
done. Its raw per-cell path (`bin_width_m: null`) is **regression-verified** to
reproduce the original shell extraction byte-for-byte (3.18M source cells, Quebrada
del Toro); the default histogram emit is verified **bit-exact** against CorraSaurus's
`reduce_cells` on the same data. The reference shell
prototype `gis/extract_source_distances.sh` is retained for now; the
**Toro-specific input prep** (geology → `lithology`, the source-area mask, snapped
points) lives in the study repo, not here.

Extracted from the Quebrada del Toro study via `git filter-repo` (history preserved).

See [HANDOFF.md](HANDOFF.md) for design rationale — the agnostic source-map
contract (binary or 0–1 scalar "production potential"), the
GravelSource boundary, and open items.

## License

GPLv3 — see [LICENSE](LICENSE).
