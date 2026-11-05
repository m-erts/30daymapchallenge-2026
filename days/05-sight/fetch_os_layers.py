"""Base-map layers for the OS-style variant: parks, major roads and rail from Overture Maps (bbox of the day's raster),
read with DuckDB straight from S3 and cached in data/raw/os_layers.gpkg (16 MB, not in git; ~2 min)."""
import time
from pathlib import Path
import duckdb, geopandas as gpd, rasterio
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "raw" / "os_layers.gpkg"
S3 = "s3://overturemaps-us-west-2/release"

def main():
    with rasterio.open(HERE / "data/raw/dtm_5m.tif") as d:
        b = d.bounds
    tr = Transformer.from_crs(27700, 4326, always_xy=True)
    xs, ys = zip(*[tr.transform(x, y) for x in (b.left, b.right) for y in (b.bottom, b.top)])
    W, S_, E, N = min(xs), min(ys), max(xs), max(ys)
    duckdb.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET http_retries = 6; SET s3_region='us-west-2';")
    rel = max(p.split("/")[4] for p, in duckdb.sql(f"FROM glob('{S3}/*/theme=base/type=land_use/*')").fetchall())
    bbox = f"bbox.xmin <= {E} AND bbox.xmax >= {W} AND bbox.ymin <= {N} AND bbox.ymax >= {S_}"
    layers = {
        "parks": f"""SELECT class, ST_AsText(geometry) AS wkt FROM read_parquet('{S3}/{rel}/theme=base/type=land_use/*', hive_partitioning=1)
                     WHERE {bbox} AND class IN ('park','garden','cemetery','grave_yard','recreation_ground','village_green',
                     'nature_reserve','golf_course','common','forest','wood','grass','meadow','allotments')
                     AND ST_GeometryType(geometry) IN ('POLYGON','MULTIPOLYGON')""",
        "roads": f"""SELECT class, ST_AsText(geometry) AS wkt FROM read_parquet('{S3}/{rel}/theme=transportation/type=segment/*', hive_partitioning=1)
                     WHERE {bbox} AND subtype = 'road' AND class IN ('motorway','trunk','primary','secondary')""",
        "rail": f"""SELECT class, ST_AsText(geometry) AS wkt FROM read_parquet('{S3}/{rel}/theme=transportation/type=segment/*', hive_partitioning=1)
                     WHERE {bbox} AND subtype = 'rail' AND class IN ('standard_gauge','narrow_gauge')""",
    }
    for name, q in layers.items():
        t = time.time()
        rows = duckdb.sql(q).fetchall()
        g = gpd.GeoDataFrame([dict(cls=c) for c, _ in rows], geometry=gpd.GeoSeries.from_wkt([w for _, w in rows], crs=4326)).to_crs(27700)
        g["release"] = rel
        g.rename(columns={"cls": "class"}).to_file(OUT, layer=name, driver="GPKG")
        print(name, len(g), f"{time.time() - t:.0f} s", flush=True)

if __name__ == "__main__":
    main()
