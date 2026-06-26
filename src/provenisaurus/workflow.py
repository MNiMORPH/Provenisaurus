"""Orchestrate the source-distance extraction (run inside a GRASS session).

    grass <location>/<mapset> --exec python -m provenisaurus config.yml
"""

from __future__ import annotations

import sys

import grass.script as gs

from . import grass_steps as G
from .config import WorkflowConfig
from .emit import iter_source_rows, open_source_cells, join_sites

_TMP = "tmp_prov"
_TMP_MAPS = [f"{_TMP}_ws", f"{_TMP}_streams", f"{_TMP}_dist_outlet",
             f"{_TMP}_dist_stream", f"{_TMP}_dist_chan",
             f"{_TMP}_src_lith", f"{_TMP}_src_dist", f"{_TMP}_src_val"]


def _ensure_basemaps(cfg: WorkflowConfig) -> str:
    """Ensure Provenisaurus's flow network exists in the mapset, building it from
    the DEM when needed; return ``"built"`` or ``"reused"``.

    Provenisaurus is the single author of ``accumulation``/``drainage``/
    ``streams``, so they are reused when already present (e.g. a ``dist_mode``
    re-run over the same DEM costs nothing extra) and only rebuilt when missing or
    when ``rebuild_basemaps`` forces it -- all three together, so the network stays
    internally consistent.  (Run after the region is set to the DEM.)
    """
    have_all = all(G.raster_exists(m)
                   for m in (cfg.accumulation, cfg.drainage, cfg.streams))
    if cfg.rebuild_basemaps or not have_all:
        G.flow_routing(cfg.dem, cfg.accumulation, cfg.drainage)
        G.extract_streams(cfg.dem, cfg.accumulation, cfg.stream_threshold, cfg.streams)
        return "built"
    return "reused"


def run(cfg: WorkflowConfig):
    """Ensure base maps, loop over the supplied sites, write the CSV.

    Returns (n_rows, n_sites).
    """
    gs.run_command("g.region", raster=cfg.dem, quiet=True)
    basemaps = _ensure_basemaps(cfg)
    gs.message(f"Base maps: {basemaps}.")
    cell_area = G.cell_area_m2()

    # Snap the raw points onto the network (or use as-is), then recover each
    # site's name from the original table by cat (snapping preserves cats).
    snapped_vec = None
    if cfg.snap_radius:
        snapped_vec = f"{_TMP}_snapped"
        G.snap_points(cfg.points, cfg.streams, cfg.accumulation,
                      cfg.snap_radius, snapped_vec)
        geom = G.points_geometry(snapped_vec)
    else:
        geom = G.points_geometry(cfg.points)
    sites = join_sites(geom, G.points_attr(cfg.points, cfg.site_column))

    # Stream each site's source cells straight to the CSV as r.stats produces
    # them -- never accumulating the whole table in memory, so a source mask
    # covering most of the map (hundreds of millions of cells) stays O(1).
    with open_source_cells(cfg.out_csv) as sink:
        try:
            for e, n, site in sites:
                distmap, _ws = G.site_distance_field(
                    cfg.drainage, cfg.streams, e, n, cfg.dist_mode, tmp=_TMP)
                with G.source_cells_stats_stream(
                        _ws, cfg.source_mask, cfg.lithology, distmap, tmp=_TMP) as lines:
                    for row in iter_source_rows(lines, site, cfg.source_indices,
                                                cell_area):
                        sink.write(row)
        finally:
            G.remove_maps(_TMP_MAPS)
            if snapped_vec:
                G.remove_vectors([snapped_vec])

    return sink.n, len(sites)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cfg = WorkflowConfig.from_yaml(argv[0]) if argv else WorkflowConfig()
    n_rows, n_sites = run(cfg)
    print(f"Wrote {cfg.out_csv}: {n_rows} source cells from {n_sites} sites "
          f"(dist_mode={cfg.dist_mode}).")


if __name__ == "__main__":
    main()
