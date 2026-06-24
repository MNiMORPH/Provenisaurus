"""Workflow configuration (GRASS-free, validated on construction)."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml


@dataclass
class WorkflowConfig:
    # input GRASS maps (the Toro-specific prep builds these; provided here by name)
    dem: str = "DEM"
    accumulation: str = "flowAccum"
    drainage: str = "drainDir"
    streams: str = "streams"
    lithology: str = "lithology"          # per-cell class (lith_index) raster
    source_mask: str = "source_mask"      # 1 where a cell is a clast source, else null
    points: str = "points"                # snapped sample points (vector)
    site_column: str = "site"
    in_basin_column: str = "in_basin"     # = 1 for in-watershed points
    # parameters
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

    @classmethod
    def from_yaml(cls, path) -> "WorkflowConfig":
        data = yaml.safe_load(Path(path).read_text()) or {}
        cfg = data.get("provenisaurus", data)   # accept a nested block or a flat mapping
        known = {f.name for f in fields(cls)}
        unknown = set(cfg) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        return cls(**cfg)
