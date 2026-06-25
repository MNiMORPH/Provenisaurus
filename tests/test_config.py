"""Unit tests for WorkflowConfig (GRASS-free)."""

import pytest

from provenisaurus.config import WorkflowConfig


def test_defaults_and_index_coercion():
    c = WorkflowConfig(source_indices=[2, 3, 4])
    assert c.dist_mode == "whole"
    assert c.source_indices == (2, 3, 4)        # coerced to a tuple of ints


def test_dist_mode_validated():
    with pytest.raises(ValueError):
        WorkflowConfig(dist_mode="sideways")


def test_snap_radius_default_and_validation():
    assert WorkflowConfig().snap_radius == 50
    assert WorkflowConfig(snap_radius=None).snap_radius is None    # skip snapping
    with pytest.raises(ValueError):
        WorkflowConfig(snap_radius=-1)


def test_empty_sources_rejected():
    with pytest.raises(ValueError):
        WorkflowConfig(source_indices=[])


def test_from_yaml_roundtrip(tmp_path):
    y = tmp_path / "cfg.yml"
    y.write_text(
        "provenisaurus:\n"
        "  dem: tandemx_toro\n"
        "  dist_mode: channel\n"
        "  source_indices: [2, 3, 4, 5, 6]\n"
        "  out_csv: /tmp/sc.csv\n"
    )
    c = WorkflowConfig.from_yaml(str(y))
    assert c.dem == "tandemx_toro"
    assert c.dist_mode == "channel"
    assert c.source_indices == (2, 3, 4, 5, 6)
    assert c.out_csv == "/tmp/sc.csv"


def test_from_yaml_rejects_unknown_keys(tmp_path):
    y = tmp_path / "cfg.yml"
    y.write_text("dem: x\nbogus_key: 1\n")
    with pytest.raises(ValueError):
        WorkflowConfig.from_yaml(str(y))


def test_rebuild_basemaps_default_is_reuse():
    assert WorkflowConfig().rebuild_basemaps is False


def test_removed_build_basemaps_key_rejected(tmp_path):
    # build_basemaps was dropped: Provenisaurus owns the flow network and reuses
    # it if present (rebuild_basemaps forces a rebuild). An old key now errors.
    y = tmp_path / "cfg.yml"
    y.write_text("provenisaurus:\n  dem: x\n  build_basemaps: true\n")
    with pytest.raises(ValueError):
        WorkflowConfig.from_yaml(str(y))
