"""Thin GRASS wrappers (the imperative shell).

Each function is a small, named wrapper around a GRASS module, so the workflow
reads as a sequence of steps and the (GRASS-free) glue stays in :mod:`emit`.
These run inside a GRASS session; importing this module needs ``grass.script``.
"""

from __future__ import annotations

import grass.script as gs


def cell_area_m2() -> float:
    """Per-cell production weight = cell area [m^2] from the current region."""
    g = gs.region()
    return float(g["ewres"]) * float(g["nsres"])


def raster_exists(name) -> bool:
    """True if a raster ``name`` is findable on the current mapset search path."""
    return bool(gs.find_file(name, element="raster")["name"])


def flow_routing(dem, accumulation, drainage, memory=8000):
    """r.watershed (SFD) -> flow accumulation + drainage direction."""
    gs.run_command("r.watershed", elevation=dem, accumulation=accumulation,
                   drainage=drainage, flags="s", memory=memory,
                   overwrite=True, quiet=True)


def extract_streams(dem, accumulation, threshold, streams, memory=4000):
    """r.stream.extract -> stream raster at the given accumulation threshold."""
    gs.run_command("r.stream.extract", elevation=dem, accumulation=accumulation,
                   threshold=threshold, stream_raster=streams, memory=memory,
                   overwrite=True, quiet=True)


def snap_points(points, streams, accumulation, radius, out, memory=1500):
    """Snap raw sample points onto the channel network (r.stream.snap).

    Returns ``out`` (a new point vector at the snapped locations; input cats are
    preserved, so site names are recovered from the original table by cat).
    """
    gs.run_command("r.stream.snap", input=points, output=out, stream_rast=streams,
                   accumulation=accumulation, radius=radius, memory=memory,
                   overwrite=True, quiet=True)
    return out


def points_geometry(vector):
    """v.out.ascii point geometry: one ``easting|northing|cat`` line per point."""
    return gs.read_command("v.out.ascii", input=vector, format="point",
                           separator="|", quiet=True)


def points_attr(vector, column):
    """v.db.select ``cat|<column>`` text (column-name header suppressed)."""
    return gs.read_command("v.db.select", map=vector, columns=f"cat,{column}",
                           separator="|", flags="c", quiet=True)


def site_distance_field(drainage, streams, e, n, dist_mode, *, tmp):
    """Per-site watershed + downstream-distance field; return (distance_map, ws).

    ``whole``   : flow distance to the outlet (hillslope + channel).
    ``channel`` : dist-to-outlet - dist-to-stream, clamped >= 0 (fluvial only).
    Writes temporary maps prefixed by ``tmp`` (removed by the caller).
    """
    ws = f"{tmp}_ws"
    gs.run_command("r.water.outlet", input=drainage, output=ws,
                   coordinates=f"{e},{n}", overwrite=True, quiet=True)
    streams_ws = f"{tmp}_streams"
    gs.mapcalc(f"{streams_ws} = {streams} * {ws}", overwrite=True, quiet=True)
    outlet = f"{tmp}_dist_outlet"
    gs.run_command("r.stream.distance", flags="o", stream_rast=streams_ws,
                   direction=drainage, method="downstream", distance=outlet,
                   overwrite=True, quiet=True)
    if dist_mode == "channel":
        stream_d = f"{tmp}_dist_stream"
        gs.run_command("r.stream.distance", stream_rast=streams_ws,
                       direction=drainage, method="downstream", distance=stream_d,
                       overwrite=True, quiet=True)
        chan = f"{tmp}_dist_chan"
        gs.mapcalc(f"{chan} = max({outlet} - {stream_d}, 0.0)", overwrite=True, quiet=True)
        return chan, ws
    return outlet, ws


def source_cells_stats(ws, source_mask, lithology, distmap, *, tmp):
    """r.stats dump '<lith_index>,<distance>,<source_value>' for source cells in
    the site's watershed (cells where both ``ws`` and ``source_mask`` are
    non-null).  ``source_value`` is the ``source_mask`` cell value -- the per-cell
    production potential (1 for a binary mask, in [0, 1] for a continuous one)."""
    src_lith = f"{tmp}_src_lith"
    src_dist = f"{tmp}_src_dist"
    src_val = f"{tmp}_src_val"
    gs.mapcalc(f"{src_lith} = if(!isnull({ws}), if(!isnull({source_mask}), "
               f"{lithology}, null()), null())", overwrite=True, quiet=True)
    gs.mapcalc(f"{src_dist} = if(!isnull({ws}), if(!isnull({source_mask}), "
               f"{distmap}, null()), null())", overwrite=True, quiet=True)
    gs.mapcalc(f"{src_val} = if(!isnull({ws}), if(!isnull({source_mask}), "
               f"{source_mask}, null()), null())", overwrite=True, quiet=True)
    return gs.read_command("r.stats", flags="1n",
                           input=f"{src_lith},{src_dist},{src_val}",
                           separator=",", quiet=True)


def remove_maps(names):
    gs.run_command("g.remove", flags="f", type="raster",
                   name=",".join(names), quiet=True)


def remove_vectors(names):
    gs.run_command("g.remove", flags="f", type="vector",
                   name=",".join(names), quiet=True)
