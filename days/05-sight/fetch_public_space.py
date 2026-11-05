"""Public space for the denominator check: every road, footway and pedestrian segment plus parks and plazas from
Overture Maps (release 2026-10-21.0, ODbL), for the London and the Paris extents of day 5. Read with DuckDB from S3.

    python fetch_public_space.py      # data/raw/public_london.gpkg, paris/data/raw/public_paris.gpkg (layers roads, areas)
"""
import sys
import time
from pathlib import Path

import duckdb
import geopandas as gpd
import rasterio
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
S3 = "s3://overturemaps-us-west-2/release"
REL = "2026-10-21.0"
CITIES = {"london": (HERE / "data/raw/dtm_5m.tif", 27700, HERE / "data/raw/public_london.gpkg"),
          "paris": (HERE / "paris/data/raw/dtm_5m.tif", 2154, HERE / "paris/data/raw/public_paris.gpkg")}
ROAD_CLASSES = ("motorway", "trunk", "primary", "secondary", "tertiary", "residential", "living_street", "unclassified",
                "pedestrian", "footway", "sidewalk", "crosswalk", "steps", "path", "cycleway", "bridleway", "service")
AREA_CLASSES = ("park", "garden", "playground", "recreation_ground", "village_green", "common", "pedestrian", "plaza",
                "dog_park", "nature_reserve")


def main(city):
    raster, crs, out = CITIES[city]
    with rasterio.open(raster) as d:
        b = d.bounds
    tr = Transformer.from_crs(crs, 4326, always_xy=True)
    xs, ys = zip(*[tr.transform(x, y) for x in (b.left, b.right) for y in (b.bottom, b.top)])
    bbox = f"bbox.xmin <= {max(xs)} AND bbox.xmax >= {min(xs)} AND bbox.ymin <= {max(ys)} AND bbox.ymax >= {min(ys)}"
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET http_retries = 6; SET s3_region='us-west-2';")
    t = time.time()
    rows = con.sql(f"""SELECT class, list_contains(flatten(list_transform(coalesce(road_flags, []), f -> f.values)), 'is_tunnel') AS tunnel,
                              ST_AsText(geometry) AS wkt
        FROM read_parquet('{S3}/{REL}/theme=transportation/type=segment/*', hive_partitioning=1)
        WHERE {bbox} AND subtype = 'road' AND class IN {ROAD_CLASSES}""").fetchall()
    roads = gpd.GeoDataFrame([dict(cls=c, tunnel=bool(tn)) for c, tn, _ in rows],
                             geometry=gpd.GeoSeries.from_wkt([w for *_, w in rows], crs=4326)).to_crs(crs)
    roads.rename(columns={"cls": "class"}).to_file(out, layer="roads", driver="GPKG")
    print(city, "roads", len(roads), f"{time.time() - t:.0f} s", flush=True)
    t = time.time()
    rows = con.sql(f"""SELECT class, ST_AsText(geometry) AS wkt
        FROM read_parquet('{S3}/{REL}/theme=base/type=land_use/*', hive_partitioning=1)
        WHERE {bbox} AND class IN {AREA_CLASSES} AND ST_GeometryType(geometry) IN ('POLYGON', 'MULTIPOLYGON')""").fetchall()
    areas = gpd.GeoDataFrame([dict(cls=c) for c, _ in rows], geometry=gpd.GeoSeries.from_wkt([w for _, w in rows], crs=4326)).to_crs(crs)
    areas.rename(columns={"cls": "class"}).to_file(out, layer="areas", driver="GPKG")
    print(city, "areas", len(areas), f"{time.time() - t:.0f} s", flush=True)


if __name__ == "__main__":
    for c in (sys.argv[1:] or list(CITIES)):
        main(c)
