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
    """Yield ``(lith_index, distance_m)`` from ``r.stats -1 -n`` two-column output.

    Lines are ``"<int>,<float>"``.  Blank lines and any cell with a null marker
    (``*``) are skipped (``-n`` should already drop nulls, but be defensive).
    """
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(",")
        if len(parts) != 2:
            continue
        cls, dist = parts[0].strip(), parts[1].strip()
        if cls in ("", "*") or dist in ("", "*"):
            continue
        yield int(cls), float(dist)


def source_rows(stats_text: str, site: str, source_indices, cell_area: float):
    """Source-cell rows for one site.

    Keep only cells whose class is a modelled source (``source_indices``), tag
    each with the site name and the per-cell production weight (``cell_area``).
    """
    sources = {int(i) for i in source_indices}
    return [SourceCell(site, cls, dist, float(cell_area))
            for cls, dist in parse_rstats(stats_text) if cls in sources]


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
