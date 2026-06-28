"""Workflow configuration (GRASS-free, validated on construction)."""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class WorkflowConfig:
    """Inputs + parameters for the source-distance extraction (validated on init).

    The caller supplies raw data + study choices (dem, lithology, source_mask,
    raw points + their site column); Provenisaurus owns the DEM-derived flow
    network (accumulation, drainage, streams) -- it builds those from the DEM,
    reuses them if already present, and rebuilds on demand (rebuild_basemaps), so
    they are named here but are *not* caller inputs. See the README "Inputs"
    section for the full contract and the parameters (incl. snap_radius,
    stream_threshold). Provenisaurus snaps the raw points onto the network it
    builds; which sites to process is the caller's choice (supply only those
    points) -- there is no in-basin filter here.
    """

    # caller inputs (raw data + study choices)
    dem: str = "DEM"
    lithology: str = "lithology"          # per-cell class (lith_index) raster
    source_mask: str = "source_mask"      # per-cell source weight: 1 (binary) or [0,1] scalar; else null
    points: str = "points"                # RAW sample points (snapped internally)
    site_column: str = "site"
    # Fluvial channel network for dist_mode="channel": a raster naming the channel
    # cells (the fluvial domain), against which the channel-only distance is split.
    # A pluggable study input mirroring source_mask -- Provenisaurus stays agnostic
    # about *where channels begin*; you supply the network. Built by
    # r.fluvial.channelheads (recommended method=dreich, DrEICH morphological heads),
    # which is the single author of the channel network and its structure. None
    # falls back to the internally-extracted stream_threshold network -- the legacy
    # fixed-accumulation-threshold proxy for the channel head (see issue #1).
    channel_network: Optional[str] = None
    # flow-network maps Provenisaurus owns: built from the DEM, reused if present,
    # rebuilt on demand. NOT caller inputs -- named here only so the maps
    # Provenisaurus writes/reads are configurable.
    accumulation: str = "flowAccum"
    drainage: str = "drainDir"
    streams: str = "streams"
    # parameters
    snap_radius: Optional[int] = 50       # r.stream.snap radius [cells]; None/0 = already on network
    stream_threshold: int = 10000         # r.stream.extract accumulation threshold [cells]
    source_indices: tuple = (2, 3, 4, 5, 6)
    dist_mode: str = "whole"              # "whole" (hillslope+channel) | "channel" (fluvial)
    rebuild_basemaps: bool = False        # force-rebuild the flow network even if it already exists
    # Distance-bin width [m] for the emitted histogram: source cells are collapsed
    # per (site, lith_index, floor(distance/bin_width_m)) into summed weight at the
    # weight-mean distance -- CorraSaurus's own reduce_cells reduction, applied at
    # the source so we never write the ~one-row-per-cell table (which reaches GBs
    # for large source masks). Default 12.0 = the DEM cell size (sub-pixel distance
    # is meaningless; CorraSaurus certifies this lossless to 1e-6). None = emit the
    # raw one-row-per-cell table (the byte-for-byte path; only for the regression).
    bin_width_m: Optional[float] = 12.0
    out_csv: str = "source_cells.csv"

    def __post_init__(self):
        self.source_indices = tuple(int(i) for i in self.source_indices)
        if self.dist_mode not in ("whole", "channel"):
            raise ValueError(f"dist_mode must be 'whole' or 'channel', got {self.dist_mode!r}")
        if not self.source_indices:
            raise ValueError("source_indices must be non-empty")
        if self.snap_radius is not None and int(self.snap_radius) < 0:
            raise ValueError("snap_radius must be >= 0 (or None to skip snapping)")
        if self.bin_width_m is not None:
            self.bin_width_m = float(self.bin_width_m)
            if self.bin_width_m <= 0:
                raise ValueError("bin_width_m must be > 0 (or None to skip binning)")

    @classmethod
    def from_yaml(cls, path) -> "WorkflowConfig":
        data = yaml.safe_load(Path(path).read_text()) or {}
        cfg = data.get("provenisaurus", data)   # accept a nested block or a flat mapping
        known = {f.name for f in fields(cls)}
        unknown = set(cfg) - known
        if unknown:
            raise ValueError(f"unknown config keys: {sorted(unknown)}")
        return cls(**cfg)
