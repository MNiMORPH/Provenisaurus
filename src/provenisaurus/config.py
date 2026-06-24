"""Workflow configuration (GRASS-free, validated on construction)."""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class WorkflowConfig:
    """Inputs + parameters for the source-distance extraction (validated on init).

    Names the existing GRASS maps the workflow reads (supplied by the caller /
    a study's prep step) and the extraction parameters. See the README "Inputs"
    section for the full contract: required maps (dem, lithology, source_mask,
    raw points, and drainage+streams unless build_basemaps), the points' site
    column, and the parameters (incl. snap_radius). Provenisaurus snaps the raw
    points onto the network it builds; which sites to process is the caller's
    choice (supply only those points) -- there is no in-basin filter here.
    """

    # input GRASS maps (the caller / a study's prep builds these; named here)
    dem: str = "DEM"
    accumulation: str = "flowAccum"
    drainage: str = "drainDir"
    streams: str = "streams"
    lithology: str = "lithology"          # per-cell class (lith_index) raster
    source_mask: str = "source_mask"      # 1 where a cell is a clast source, else null
    points: str = "points"                # RAW sample points (snapped internally)
    site_column: str = "site"
    # parameters
    snap_radius: Optional[int] = 50       # r.stream.snap radius [cells]; None/0 = already on network
    stream_threshold: int = 10000         # r.stream.extract accumulation threshold [cells]
    source_indices: tuple = (2, 3, 4, 5, 6)
    dist_mode: str = "whole"              # "whole" (hillslope+channel) | "channel" (fluvial)
    build_basemaps: bool = False          # (re)build flow routing + streams from the DEM
    out_csv: str = "source_cells.csv"

    def __post_init__(self):
        self.source_indices = tuple(int(i) for i in self.source_indices)
        if self.dist_mode not in ("whole", "channel"):
            raise ValueError(f"dist_mode must be 'whole' or 'channel', got {self.dist_mode!r}")
        if not self.source_indices:
            raise ValueError("source_indices must be non-empty")
        if self.snap_radius is not None and int(self.snap_radius) < 0:
            raise ValueError("snap_radius must be >= 0 (or None to skip snapping)")

    @classmethod
    def from_yaml(cls, path) -> "WorkflowConfig":
        data = yaml.safe_load(Path(path).read_text()) or {}
        cfg = data.get("provenisaurus", data)   # accept a nested block or a flat mapping
        known = {f.name for f in fields(cls)}
        unknown = set(cfg) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        return cls(**cfg)
