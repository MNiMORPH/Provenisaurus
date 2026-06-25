"""Orchestrate the source-distance extraction (run inside a GRASS session).

    grass <location>/<mapset> --exec python -m provenisaurus config.yml
"""

from __future__ import annotations

import sys

import grass.script as gs

from . import grass_steps as G
from .config import WorkflowConfig
from .emit import source_rows, write_source_cells, join_sites

_TMP = "tmp_prov"
_TMP_MAPS = [f"{_TMP}_ws", f"{_TMP}_streams", f"{_TMP}_dist_outlet",
             f"{_TMP}_dist_stream", f"{_TMP}_dist_chan",
             f"{_TMP}_src_lith", f"{_TMP}_src_dist", f"{_TMP}_src_val"]


def run(cfg: WorkflowConfig):
    """Build (optionally) base maps, loop over in-basin sites, write the CSV.

    Returns (n_rows, n_sites).
    """
    if cfg.build_basemaps:
        G.flow_routing(cfg.dem, cfg.accumulation, cfg.drainage)
        G.extract_streams(cfg.dem, cfg.accumulation, cfg.stream_threshold, cfg.streams)

    gs.run_command("g.region", raster=cfg.dem, quiet=True)
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

    rows = []
    try:
        for e, n, site in sites:
            distmap, _ws = G.site_distance_field(
                cfg.drainage, cfg.streams, e, n, cfg.dist_mode, tmp=_TMP)
            stats = G.source_cells_stats(
                _ws, cfg.source_mask, cfg.lithology, distmap, tmp=_TMP)
            rows.extend(source_rows(stats, site, cfg.source_indices, cell_area))
    finally:
        G.remove_maps(_TMP_MAPS)
        if snapped_vec:
            G.remove_vectors([snapped_vec])

    n_rows = write_source_cells(rows, cfg.out_csv)
    return n_rows, len(sites)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cfg = WorkflowConfig.from_yaml(argv[0]) if argv else WorkflowConfig()
    n_rows, n_sites = run(cfg)
    print(f"Wrote {cfg.out_csv}: {n_rows} source cells from {n_sites} sites "
          f"(dist_mode={cfg.dist_mode}).")


if __name__ == "__main__":
    main()
