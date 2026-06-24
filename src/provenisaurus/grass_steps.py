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


def list_sites(points, site_column, in_basin_column):
    """[(easting, northing, site)] for sample points flagged in-basin (==1).

    v.out.ascii point format is ``E|N|cat|<site>|<in_basin>``.
    """
    txt = gs.read_command("v.out.ascii", input=points,
                          columns=f"{site_column},{in_basin_column}",
                          format="point", separator="|", quiet=True)
    out = []
    for line in txt.splitlines():
        f = line.strip().split("|")
        if len(f) < 5:
            continue
        e, n, _cat, site, in_basin = f[0], f[1], f[2], f[3], f[4]
        if in_basin.strip() == "1":
            out.append((e, n, site))
    return out


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
    """r.stats dump '<lith_index>,<distance>' for source cells in the site's
    watershed (cells where both ``ws`` and ``source_mask`` are non-null)."""
    src_lith = f"{tmp}_src_lith"
    src_dist = f"{tmp}_src_dist"
    gs.mapcalc(f"{src_lith} = if(!isnull({ws}), if(!isnull({source_mask}), "
               f"{lithology}, null()), null())", overwrite=True, quiet=True)
    gs.mapcalc(f"{src_dist} = if(!isnull({ws}), if(!isnull({source_mask}), "
               f"{distmap}, null()), null())", overwrite=True, quiet=True)
    return gs.read_command("r.stats", flags="1n", input=f"{src_lith},{src_dist}",
                           separator=",", quiet=True)


def remove_maps(names):
    gs.run_command("g.remove", flags="f", type="raster",
                   name=",".join(names), quiet=True)
