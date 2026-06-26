"""Unit tests for the GRASS-free emit core (no GRASS needed)."""

import csv

import pytest

from provenisaurus.emit import (
    SOURCE_CELLS_HEADER, SourceCell, parse_rstats, source_rows,
    histogram_rows, write_source_cells, parse_cat_attr, join_sites)


def test_parse_rstats_basic():
    text = "5,79.882,1\n5,91.882,1\n4,200.0,1\n"
    assert list(parse_rstats(text)) == [(5, 79.882, 1.0), (5, 91.882, 1.0),
                                        (4, 200.0, 1.0)]


def test_parse_rstats_skips_blank_and_null():
    text = "5,79.882,1\n\n*,*,*\n4,200.0,1\n   \n"
    assert list(parse_rstats(text)) == [(5, 79.882, 1.0), (4, 200.0, 1.0)]


def test_parse_rstats_reads_scalar_potential():
    assert list(parse_rstats("5,79.882,0.3\n")) == [(5, 79.882, 0.3)]


def test_parse_rstats_rejects_value_above_one():
    with pytest.raises(ValueError):
        list(parse_rstats("5,79.882,1.5\n"))


def test_parse_rstats_rejects_negative_value():
    with pytest.raises(ValueError):
        list(parse_rstats("5,79.882,-0.1\n"))


def test_parse_rstats_clamps_float_noise_above_one():
    # a 1.0000000000001 from an upstream x/max(x) rescale is float noise, not a
    # malformed map: clamp to the bound rather than reject the whole extraction
    assert list(parse_rstats("5,79.882,1.0000000000001\n")) == [(5, 79.882, 1.0)]


def test_parse_rstats_clamps_tiny_negative_to_zero():
    assert list(parse_rstats("5,79.882,-0.0000001\n")) == [(5, 79.882, 0.0)]


def test_parse_rstats_still_raises_beyond_tolerance():
    # past the bound by more than the tolerance -> still a genuine error
    with pytest.raises(ValueError):
        list(parse_rstats("5,79.882,1.00001\n"))


def test_source_rows_filters_to_sources_and_tags():
    # lith 1 (conglomerate) and 7 are not modelled sources -> dropped
    text = "5,79.882,1\n1,50.0,1\n4,200.0,1\n7,10.0,1\n"
    rows = source_rows(text, "S1", source_indices=[2, 3, 4, 5, 6], cell_area=144.0)
    assert [(r.lith_index, r.distance_m) for r in rows] == [(5, 79.882), (4, 200.0)]
    assert all(r.site == "S1" and r.weight == 144.0 for r in rows)


def test_source_rows_empty_when_no_sources():
    rows = source_rows("1,50.0,1\n7,10.0,1\n", "S2", [2, 3, 4, 5, 6], 144.0)
    assert rows == []


def test_source_rows_binary_mask_gives_uniform_cell_area():
    # a binary mask stores value 1 -> weight is exactly cell_area (the special
    # case of the general weight = cell_area * source_value)
    rows = source_rows("5,79.882,1\n", "S1", [5], cell_area=144.0)
    assert rows[0].weight == 144.0


def test_source_rows_scalar_potential_scales_weight():
    # a continuous [0, 1] potential scales the per-cell weight down
    rows = source_rows("5,79.882,0.3\n", "S1", [5], cell_area=144.0)
    assert rows[0].weight == pytest.approx(144.0 * 0.3)


def test_write_source_cells_roundtrip(tmp_path):
    rows = source_rows("5,79.882,1\n4,200.0,1\n", "S1", [4, 5], cell_area=144.0)
    out = tmp_path / "source_cells.csv"
    n = write_source_cells(rows, str(out))
    assert n == 2
    with open(out, newline="") as f:
        r = list(csv.reader(f))
    assert tuple(r[0]) == SOURCE_CELLS_HEADER
    # whole-number weight printed without trailing .0; distance to 3 decimals
    assert r[1] == ["S1", "5", "79.882", "144"]
    assert r[2] == ["S1", "4", "200.000", "144"]
    # LF line endings, not csv's default CRLF (so output matches the shell script)
    assert b"\r" not in out.read_bytes()


def test_histogram_rows_bins_sum_weight_and_weight_mean_distance():
    # lith 5: cells at 3 and 9 share bin 0 (floor(d/12)); 20 falls in bin 1.
    # lith 1 is not a source -> dropped.  Rows come out in (lith, bin) order.
    text = "5,3.0,1\n5,9.0,1\n5,20.0,1\n1,4.0,1\n"
    rows = list(histogram_rows(text.splitlines(), "S1", [2, 3, 4, 5, 6],
                               cell_area=144.0, bin_width_m=12.0))
    # bin 0: weight 144+144=288, weight-mean distance (3+9)/2 = 6.0
    # bin 1: weight 144, distance 20.0
    assert rows == [SourceCell("S1", 5, 6.0, 288.0),
                    SourceCell("S1", 5, 20.0, 144.0)]


def test_histogram_rows_scalar_potential_weights_the_mean():
    # continuous [0,1] potential: weights are cell_area*value, and the mean
    # distance is weighted by them
    rows = list(histogram_rows(["5,4.0,0.25", "5,8.0,0.75"], "S1", [5],
                               cell_area=100.0, bin_width_m=12.0))
    # weights 25 and 75 -> sum 100; mean (25*4 + 75*8)/100 = 7.0
    assert rows == [SourceCell("S1", 5, 7.0, 100.0)]


def test_histogram_rows_matches_corrasaurus_reduce_cells():
    # the emitted histogram must equal CorraSaurus's reduce_cells reduction --
    # same floor(d/bin) binning, summed weight, weight-mean distance
    pytest.importorskip("corrasaurus")
    from corrasaurus.model import SourceCells, reduce_cells
    import numpy as np
    text = "\n".join(["5,3.0,1", "5,9.0,1", "5,20.0,1", "4,5.0,1", "4,5.5,1"])
    got = sorted((r.lith_index, round(r.distance_m, 9), r.weight)
                 for r in histogram_rows(text.splitlines(), "S1", [4, 5],
                                         cell_area=144.0, bin_width_m=12.0))
    cells = SourceCells(
        np.zeros(5, int), np.array([5, 5, 5, 4, 4]),
        np.array([3.0, 9.0, 20.0, 5.0, 5.5]), np.full(5, 144.0),
        n_sites=1, n_liths=7)
    red = reduce_cells(cells, bin_width_m=12.0)
    want = sorted((int(li), round(float(d), 9), float(w))
                  for li, d, w in zip(red.lith_idx, red.distance, red.weight))
    assert got == want


def test_join_sites_by_cat():
    geom = "212406|7293834|1\n218898|7268238|2\n"
    attr = "1|AW14-SB-CC\n2|AW15_28_CC\n"
    assert join_sites(geom, attr) == [("212406", "7293834", "AW14-SB-CC"),
                                      ("218898", "7268238", "AW15_28_CC")]


def test_join_sites_skips_unmatched_cat():
    # snapping preserves cats; a geometry cat with no site row is dropped
    assert join_sites("10|20|1\n30|40|9\n", "1|S1\n") == [("10", "20", "S1")]


def test_parse_cat_attr_ignores_header():
    assert parse_cat_attr("cat|site\n1|S1\n2|S2\n") == {"1": "S1", "2": "S2"}


def test_write_distance_rounding(tmp_path):
    rows = source_rows("5,79.8825,1\n", "S1", [5], cell_area=12.5)
    out = tmp_path / "sc.csv"
    write_source_cells(rows, str(out), distance_decimals=2)
    with open(out, newline="") as f:
        last = list(csv.reader(f))[-1]
    assert last == ["S1", "5", "79.88", "12.5"]   # non-integer weight kept
