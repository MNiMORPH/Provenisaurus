"""Unit tests for the GRASS-free emit core (no GRASS needed)."""

import csv

import pytest

from provenisaurus.emit import (
    SOURCE_CELLS_HEADER, parse_rstats, source_rows, write_source_cells)


def test_parse_rstats_basic():
    text = "5,79.882\n5,91.882\n4,200.0\n"
    assert list(parse_rstats(text)) == [(5, 79.882), (5, 91.882), (4, 200.0)]


def test_parse_rstats_skips_blank_and_null():
    text = "5,79.882\n\n*,*\n4,200.0\n   \n"
    assert list(parse_rstats(text)) == [(5, 79.882), (4, 200.0)]


def test_source_rows_filters_to_sources_and_tags():
    # lith 1 (conglomerate) and 7 are not modelled sources -> dropped
    text = "5,79.882\n1,50.0\n4,200.0\n7,10.0\n"
    rows = source_rows(text, "S1", source_indices=[2, 3, 4, 5, 6], cell_area=144.0)
    assert [(r.lith_index, r.distance_m) for r in rows] == [(5, 79.882), (4, 200.0)]
    assert all(r.site == "S1" and r.weight == 144.0 for r in rows)


def test_source_rows_empty_when_no_sources():
    rows = source_rows("1,50.0\n7,10.0\n", "S2", [2, 3, 4, 5, 6], 144.0)
    assert rows == []


def test_write_source_cells_roundtrip(tmp_path):
    rows = source_rows("5,79.882\n4,200.0\n", "S1", [4, 5], cell_area=144.0)
    out = tmp_path / "source_cells.csv"
    n = write_source_cells(rows, str(out))
    assert n == 2
    with open(out, newline="") as f:
        r = list(csv.reader(f))
    assert tuple(r[0]) == SOURCE_CELLS_HEADER
    # whole-number weight printed without trailing .0; distance to 3 decimals
    assert r[1] == ["S1", "5", "79.882", "144"]
    assert r[2] == ["S1", "4", "200.000", "144"]


def test_write_distance_rounding(tmp_path):
    rows = source_rows("5,79.8825\n", "S1", [5], cell_area=12.5)
    out = tmp_path / "sc.csv"
    write_source_cells(rows, str(out), distance_decimals=2)
    with open(out, newline="") as f:
        last = list(csv.reader(f))[-1]
    assert last == ["S1", "5", "79.88", "12.5"]   # non-integer weight kept
