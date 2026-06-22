#!/bin/sh
#
# extract_source_distances.sh
# ---------------------------
# Build the per-site source-cell table that feeds the clast-attrition inversion:
# one row per upstream source cell (site, lith_index, distance_m, weight) ->
# data/derived/source_cells.csv.  This is the only GIS product the Python model
# needs; the forward model and inversion have no GRASS dependency.
#
# Only the 32 clast sites inside the Toro watershed (above Campo Quijano) are
# processed; the other 45 regional sites (Humahuaca/Iruya etc.) lack geology and
# source mapping and are a future extension.
#
# Generalises the by-hand AnalysisAGU2020.sh (3 sites, slope>30 deg proxy) to all
# in-basin sites with the Tofelde (2018) hillslope-process classes as sources.
#
# v1 model decisions (Wickert / Roth, June 2026):
#   D1 stream threshold : configurable; run a sensitivity test -- it matters most
#                         for the channel-only D6 variant (sets where channels,
#                         hence attrition, begin).
#   D2 snap radius      : 50 cells (kept from AnalysisAGU2020.sh; tighten later).
#   D3 flow routing     : r.watershed SFD drainage direction (drainDir).
#   D5 production weight : uniform = cell area (pluggable: swap source_mask for a
#                         continuous clast-generation-potential raster later).
#   D6 attrition path   : WHOLE flow path (hillslope+channel) for v1 simplicity.
#                         Channel-only (D. Roth: hillslope transport is a
#                         different process) is provided, commented, in the loop.
#
# RUN INSIDE the GRASS Toro location (UTM 20S / WGS84, EPSG:32720):
#   export PROJ_DATA=/usr/share/proj GDAL_DATA=/usr/share/gdal; unset PROJ_LIB
#   grass ~/Dropbox/grassdata/Toro-Lithology-Fining/PERMANENT \
#         --exec sh gis/extract_source_distances.sh
# -----------------------------------------------------------------------------
set -e

# ----------------------------- configuration ---------------------------------
DEM=tandemx_toro
STREAM_THRESHOLD=10000        # r.stream.extract accumulation threshold (cells); ~1.44 km^2 @ 12 m [D1]
SNAP_RADIUS=50                # r.stream.snap radius (cells) [D2]
SOURCE_LITHS="2 3 4 5 6"      # source lithologies (no conglomerate=1)
OUTLET=230854.95278412075,7242785.076394613   # Campo Quijano (Toro outlet) [Andy]
OUT_CSV="$(pwd)/data/derived/source_cells.csv"

PROJDIR="${PROJDIR:-$HOME/Dropbox/Papers/InProgress/ClastsLithologyFiningToro}"
GEOL_GPKG="${GEOL_GPKG:-$PROJDIR/github/GeologicalMap-QuebradaDelToro/GeologicalMap_QuebradaDelToro_UTM20S_WGS84.gpkg}"
GEOL_LAYER=geomapFleagle_UTM20S_WGS84
LITH_COLUMN=lith_index
SOURCE_KMZ_DIR="${SOURCE_KMZ_DIR:-$PROJDIR/GIS/Tofelde2018_HillslopeProcessClassification}"
# "file:layer" pairs (note the Scree KMZ's internal layer is lowercase 'scree').
SOURCE_CLASSES="Landslide:Landslide Scree:scree Steep_slope_gullies:Steep_slope_gullies Low_slope_gullies:Low_slope_gullies"
CLAST_KML="${CLAST_KML:-$PROJDIR/ClastCounts/ClastCounts.kml}"

# ------------------------------- IMPORT --------------------------------------
# Run once; comment out this block on re-runs once the maps exist.
g.region -p raster="$DEM"

# Flow routing: r.watershed SFD -> accumulation + drainage direction [D3].
r.watershed elevation="$DEM" accumulation=flowAccum drainage=drainDir -s memory=8000 --o

# Channel network (re-using the accumulation for consistency).
r.stream.extract elevation="$DEM" accumulation=flowAccum threshold="$STREAM_THRESHOLD" \
    stream_raster=streams memory=4000 --o

# Toro watershed above Campo Quijano -> restricts processing to in-basin sites.
r.water.outlet input=drainDir output=watershed_Toro coordinates="$OUTLET" --o

# Geology -> lithology raster.
v.import input="$GEOL_GPKG" layer="$GEOL_LAYER" output=geology --o
v.to.rast input=geology output=lithology use=attr attribute_column="$LITH_COLUMN" --o

# Tofelde clast-source classes -> unioned binary source mask.
SRC_PATCH=""
for entry in $SOURCE_CLASSES; do
    cls="${entry%%:*}"; lyr="${entry##*:}"
    v.import input="$SOURCE_KMZ_DIR/${cls}.kmz" layer="$lyr" output="src_${cls}" --o
    SRC_PATCH="$SRC_PATCH src_${cls}"
done
v.patch -e input=$(echo $SRC_PATCH | tr ' ' ',') output=source_areas --o
v.to.rast input=source_areas output=source_mask use=val value=1 --o

# Clast points: snap to channels, re-attach site by category, flag in-basin sites.
v.import input="$CLAST_KML" output=ClastCounts --o
r.stream.snap input=ClastCounts output=ClastCounts_snapped \
    stream_rast=streams accumulation=flowAccum radius="$SNAP_RADIUS" memory=1500 --o
v.db.addtable map=ClastCounts_snapped --o
v.db.join map=ClastCounts_snapped column=cat \
    other_table=ClastCounts other_column=cat subset_columns=site --o
v.what.rast map=ClastCounts_snapped raster=watershed_Toro column=in_toro
# -----------------------------------------------------------------------------

# Per-cell production weight.  v1: uniform = cell area [m^2] [D5].
eval "$(g.region -g)"
CELL_AREA=$(awk "BEGIN{print $ewres*$nsres}")

mkdir -p "$(dirname "$OUT_CSV")"
echo "site,lith_index,distance_m,weight" > "$OUT_CSV"

# Process only in-watershed sites:  E|N|cat|site|in_toro
POINTS=$(v.out.ascii input=ClastCounts_snapped columns=site,in_toro format=point separator='|' --q)

echo "$POINTS" | while IFS='|' read -r E N CAT SITE IN; do
    [ "$IN" = "1" ] || continue
    echo ">> site=$SITE  cat=$CAT  E=$E N=$N"

    # 1. Watershed upstream of this site, and its channel network.
    r.water.outlet input=drainDir output=tmp_ws coordinates="$E,$N" --o --q
    r.mapcalc "tmp_streams = streams * tmp_ws" --o --q

    # 2. WHOLE-PATH downstream distance to the site (= outlet of the masked
    #    network).  -o => distance to outlet [D6 v1].
    r.stream.distance -o stream_rast=tmp_streams direction=drainDir \
        method=downstream distance=tmp_dist_outlet --o --q
    DISTMAP=tmp_dist_outlet

    # --- D6 v2 (channel-only attrition, D. Roth): uncomment the 3 lines below to
    #     strip the hillslope leg so Sternberg acts only along the channel.
    # r.stream.distance stream_rast=tmp_streams direction=drainDir \
    #     method=downstream distance=tmp_dist_stream --o --q     # hillslope leg
    # r.mapcalc "tmp_dist_chan = tmp_dist_outlet - tmp_dist_stream" --o --q
    # DISTMAP=tmp_dist_chan
    # ---

    # 3. Keep source cells in this watershed, tagged by lithology + distance.
    r.mapcalc "tmp_src_lith = if(tmp_ws && source_mask, lithology, null())" --o --q
    r.mapcalc "tmp_src_dist = if(tmp_ws && source_mask, $DISTMAP, null())" --o --q

    # 4. One row per source cell of a modelled lithology.
    r.stats -1 -n input=tmp_src_lith,tmp_src_dist separator=',' --q \
      | awk -F',' -v site="$SITE" -v w="$CELL_AREA" -v liths=" $SOURCE_LITHS " '
            index(liths, " " $1 " ") { printf "%s,%d,%.3f,%s\n", site, $1, $2, w }' \
      >> "$OUT_CSV"
done

echo "Wrote $OUT_CSV"
g.remove -f type=raster \
    name=tmp_ws,tmp_streams,tmp_dist_outlet,tmp_dist_stream,tmp_dist_chan,tmp_src_lith,tmp_src_dist \
    2>/dev/null || true
