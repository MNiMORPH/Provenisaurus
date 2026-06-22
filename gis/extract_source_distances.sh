#!/bin/sh
#
# extract_source_distances.sh
# ---------------------------
# Build the per-site source-cell table that feeds the clast-attrition inversion.
#
# For every clast-count sample site this script:
#   1. delineates the contributing watershed upstream of the site,
#   2. computes the downstream flow distance from every cell to the site,
#   3. keeps only "source" cells -- mapped clast-generation areas intersected
#      with the source lithologies,
#   4. writes one row per source cell: site, lith_index, distance_m, weight.
#
# The result, data/derived/source_cells.csv, is the only GIS product the Python
# model needs; the forward model and inversion have no GRASS dependency.
#
# This generalises the by-hand AnalysisAGU2020.sh (which did three sites with
# slope>30 deg as the source proxy) to all sites with the Tofelde (2018)
# hillslope-process classes as mapped clast sources.
#
# RUN INSIDE the GRASS Toro location (UTM 20S / WGS84, EPSG:32720), e.g.:
#   grass /path/to/grassdata/Salta_UTM20S/toro --exec sh gis/extract_source_distances.sh
#
# Prerequisites in the mapset (import once; see the "IMPORT" block below):
#   - DEM raster                 : $DEM
#   - geological map vector       : with integer column $LITH_COLUMN (lith_index)
#   - Tofelde source polygons     : the *.kmz hillslope-process classes
#   - clast-count points          : ClastCounts.kml
#
# -----------------------------------------------------------------------------
set -e

# ----------------------------- configuration ---------------------------------
DEM=tandemx_toro                  # input DEM raster (already in mapset)
LITH_VECTOR=lithology             # geological-map vector (already in mapset)
LITH_COLUMN=lith_index            # integer lithology code column
STREAM_THRESHOLD=10000            # r.stream.extract accumulation threshold (cells)
SNAP_RADIUS=50                    # r.stream.snap search radius (cells)
SOURCE_LITHS="2 3 4 5 6"          # modelled source lithology codes (no conglomerate=1)
OUT_CSV="$(pwd)/data/derived/source_cells.csv"

# Tofelde (2018) hillslope-process classes to treat as clast sources.
# (Andy: all four selected; swap to a continuous generation-potential raster
#  later by replacing $SOURCE_MASK below -- nothing downstream changes.)
SOURCE_KMZ_DIR="${SOURCE_KMZ_DIR:-$HOME/Dropbox/Papers/InProgress/ClastsLithologyFiningToro/GIS/Tofelde2018_HillslopeProcessClassification}"
SOURCE_CLASSES="Landslide Scree Steep_slope_gullies Low_slope_gullies"

CLAST_KML="${CLAST_KML:-$HOME/Dropbox/Papers/InProgress/ClastsLithologyFiningToro/ClastCounts/ClastCounts.kml}"

# ------------------------------- IMPORT --------------------------------------
# Run this block once.  Comment it out on re-runs once the maps exist.
g.region -p raster="$DEM"

# Rasterise the geological map to lithology codes.
v.to.rast input="$LITH_VECTOR" output=lithology use=attr attribute_column="$LITH_COLUMN" --o

# Import and union the Tofelde clast-source polygons -> binary source mask.
SRC_PATCH=""
for cls in $SOURCE_CLASSES; do
    v.import input="$SOURCE_KMZ_DIR/${cls}.kmz" output="src_${cls}" --o
    SRC_PATCH="$SRC_PATCH src_${cls}"
done
v.patch -e input=$(echo $SRC_PATCH | tr ' ' ',') output=source_areas --o
v.to.rast input=source_areas output=source_mask use=val value=1 --o

# Stream network + flow directions.
r.stream.extract elevation="$DEM" threshold="$STREAM_THRESHOLD" \
    stream_raster=streams direction=flowdir memory=4000 --o

# Clast-count points, snapped to the channel network for correct watershed
# delineation.  ClastCounts.kml carries a "site" attribute that matches
# ClastCounts.txt exactly (verified: all 77 names identical).  r.stream.snap
# preserves point categories, so we re-attach "site" from the original table by
# category -- exact even for the two sites that share coordinates
# (AW14-Jualla2-DS / AndyCC-Jueya), because they keep distinct categories.
v.import input="$CLAST_KML" output=ClastCounts --o
r.stream.snap input=ClastCounts output=ClastCounts_snapped \
    stream_rast=streams radius="$SNAP_RADIUS" memory=1500 --o
v.db.addtable map=ClastCounts_snapped --o
v.db.join map=ClastCounts_snapped column=cat \
    other_table=ClastCounts other_column=cat subset_columns=site --o
# -----------------------------------------------------------------------------

# Per-cell source-production weight.  v1: uniform = cell area [m^2].
EWRES=$(g.region -g | sed -n 's/^ewres=//p')
NSRES=$(g.region -g | sed -n 's/^nsres=//p')
CELL_AREA=$(awk "BEGIN{print $EWRES*$NSRES}")

# Fresh output file with header.
mkdir -p "$(dirname "$OUT_CSV")"
echo "site,lith_index,distance_m,weight" > "$OUT_CSV"

# Dump snapped points as "easting|northing|cat|site".
POINTS=$(v.out.ascii input=ClastCounts_snapped columns=site format=point separator='|' --q)

echo "$POINTS" | while IFS='|' read -r E N CAT SITE; do
    [ -z "$E" ] && continue
    echo ">> site=$SITE  cat=$CAT  E=$E N=$N"

    # 1. Watershed upstream of this sample point.
    r.water.outlet input=flowdir output=tmp_ws coordinates="$E,$N" --o --q

    # 2. Downstream flow distance from every cell to the site (the outlet of the
    #    masked network).  -o => distance to outlet; method=downstream.
    r.mapcalc "tmp_streams = streams * tmp_ws" --o --q
    r.stream.distance -o stream_rast=tmp_streams direction=flowdir \
        method=downstream distance=tmp_flowdist --o --q

    # 3. Keep only source cells (mapped source areas) inside this watershed,
    #    tagged by lithology and by distance.
    r.mapcalc "tmp_src_lith = if(tmp_ws && source_mask, lithology, null())" --o --q
    r.mapcalc "tmp_src_dist = if(tmp_ws && source_mask, tmp_flowdist, null())" --o --q

    # 4. One row per source cell: lith_index, distance_m.  Prepend site, append
    #    weight.  Restrict to modelled source lithologies.
    r.stats -1 -n input=tmp_src_lith,tmp_src_dist separator=',' --q \
      | awk -F',' -v site="$SITE" -v w="$CELL_AREA" -v liths=" $SOURCE_LITHS " '
            index(liths, " " $1 " ") { printf "%s,%d,%.3f,%s\n", site, $1, $2, w }' \
      >> "$OUT_CSV"
done

echo "Wrote $OUT_CSV"
g.remove -f type=raster name=tmp_ws,tmp_streams,tmp_flowdist,tmp_src_lith,tmp_src_dist 2>/dev/null || true
