"""Provenisaurus -- sediment provenance + transport-distance extraction (GRASS).

Per sample site, the upstream distribution of source area vs. downstream
transport distance for each class, emitted as the long-format ``source_cells.csv``
(``site, lith_index, distance_m, weight``) that CorraSaurus inverts.

This package follows a functional-core / imperative-shell split: the GRASS-free
glue that turns ``r.stats`` output into source-cell rows lives in :mod:`emit`
(pure, unit-tested); the GRASS module orchestration lives behind thin wrappers.
"""

from .emit import (
    SourceCell, SOURCE_CELLS_HEADER, parse_rstats, source_rows, write_source_cells,
)
from .config import WorkflowConfig

__all__ = [
    "WorkflowConfig",
    "SourceCell", "SOURCE_CELLS_HEADER",
    "parse_rstats", "source_rows", "write_source_cells",
]
