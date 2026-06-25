"""GRASS-free glue: r.stats output -> source_cells rows -> long-format CSV.

The GRASS workflow tags each source cell with its class (``lith_index``) and its
downstream transport distance, then dumps them with::

    r.stats -1 -n input=<class_map>,<distance_map> separator=','

giving one ``lith_index,distance_m`` line per source cell.  This module turns
that raw dump into the ``source_cells.csv`` (``site, lith_index, distance_m,
weight``) that CorraSaurus consumes -- the parsing / class-filtering /
area-weighting / CSV assembly that used to live in awk, isolated here as pure
functions so they are unit-testable without GRASS.
"""

from __future__ import annotations

import csv
from typing import NamedTuple

#: Long-format source-cell table columns.
SOURCE_CELLS_HEADER = ("site", "lith_index", "distance_m", "weight")


class SourceCell(NamedTuple):
    site: str
    lith_index: int
    distance_m: float
    weight: float


def parse_rstats(text: str):
    """Yield ``(lith_index, distance_m, source_value)`` from ``r.stats -1 -n``
    three-column output.

    Lines are ``"<int>,<float>,<float>"`` -- class, downstream distance, and the
    source cell's production potential (the ``source_mask`` cell value: ``1`` for
    a binary mask, in ``[0, 1]`` for a continuous one).  Blank lines and any cell
    with a null marker (``*``) are skipped (``-n`` should already drop nulls, but
    be defensive).  ``source_value`` must lie in ``[0, 1]``; a value outside that
    range raises ``ValueError`` (the source map is malformed -- callers wanting a
    different convention should adjust the map, not the weight).
    """
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != 3:
            continue
        cls, dist, val = (p.strip() for p in parts)
        if cls in ("", "*") or dist in ("", "*") or val in ("", "*"):
            continue
        value = float(val)
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"source_mask value {value!r} outside [0, 1] "
                f"(lith_index {cls}, distance {dist})")
        yield int(cls), float(dist), value


def source_rows(stats_text: str, site: str, source_indices, cell_area: float):
    """Source-cell rows for one site.

    Keep only cells whose class is a modelled source (``source_indices``), tag
    each with the site name and the per-cell production weight,
    ``cell_area * source_value``.  A binary mask has ``source_value == 1``, so the
    weight is the uniform ``cell_area``; a continuous [0, 1] potential scales it
    down (a "0.3 likely a source" cell contributes 0.3x the weight).
    """
    sources = {int(i) for i in source_indices}
    return [SourceCell(site, cls, dist, cell_area * value)
            for cls, dist, value in parse_rstats(stats_text) if cls in sources]


def parse_points(geom_text: str):
    """[(easting, northing, cat)] from ``v.out.ascii format=point`` (``E|N|cat``)."""
    out = []
    for line in geom_text.splitlines():
        f = line.strip().split("|")
        if len(f) >= 3 and f[0]:
            out.append((f[0], f[1], f[2]))
    return out


def parse_cat_attr(attr_text: str):
    """``{cat: value}`` from ``v.db.select -c columns=cat,<col> separator='|'``.

    A leading ``cat`` header (if column names weren't suppressed) is ignored.
    """
    m = {}
    for line in attr_text.splitlines():
        f = line.strip().split("|")
        if len(f) >= 2 and f[0] and f[0] != "cat":
            m[f[0]] = f[1]
    return m


def join_sites(geom_text: str, attr_text: str):
    """[(easting, northing, site)] joining point geometry to site names by cat.

    ``geom_text`` is the (possibly snapped) point geometry; ``attr_text`` is the
    original points' ``cat,site`` table.  Snapping preserves cats, so the snapped
    geometry is matched back to its site name through the cat.
    """
    cat_site = parse_cat_attr(attr_text)
    return [(e, n, cat_site[c]) for e, n, c in parse_points(geom_text) if c in cat_site]


def _fmt_weight(w: float) -> str:
    """Drop a trailing ``.0`` on whole-number weights (e.g. 144.0 -> '144')."""
    return str(int(w)) if float(w).is_integer() else repr(float(w))


def write_source_cells(rows, path, *, distance_decimals: int = 3) -> int:
    """Write rows to a long-format CSV (header + one row per source cell).

    Returns the number of data rows written.  Distances are rounded to
    ``distance_decimals`` places (matching the original extraction).
    """
    fmt = f"{{:.{distance_decimals}f}}"
    with open(path, "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")   # LF (not csv's default CRLF)
        w.writerow(SOURCE_CELLS_HEADER)
        n = 0
        for r in rows:
            w.writerow([r.site, int(r.lith_index), fmt.format(r.distance_m),
                        _fmt_weight(r.weight)])
            n += 1
    return n
