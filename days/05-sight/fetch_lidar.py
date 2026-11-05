"""Day 5 (Senses: Sight): download Environment Agency LiDAR composites for the LVMF extent.

Pulls the 1 m first-return DSM and the 1 m DTM through Defra's WCS, resampled server-side
(nearest neighbour, which the server uses by default) to CELL metres, in 5 x 5 km tiles,
then mosaics them to data/raw/dsm_5m.tif and data/raw/dtm_5m.tif (EPSG:27700).

    python fetch_lidar.py            # ~40 requests, ~2 min

Licence of both rasters: Open Government Licence v3, (c) Environment Agency copyright and/or
database right 2022. Composite flights: DSM 2016-11-11 .. 2022-05-05, DTM 2000-06-06 .. 2022-04-02.
"""
from pathlib import Path
import sys
import time
import urllib.request

import numpy as np
import rasterio
from rasterio.transform import from_origin

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
CELL = 5                                   # metres; the WCS scale factor is 1/CELL
# extent in British National Grid: every LVMF protected vista plus a margin (metres)
E0, E1, N0, N1 = 517800, 539800, 172400, 190800
TILE = 5000

WCS = {
    "dsm": ("https://environment.data.gov.uk/spatialdata/lidar-composite-digital-surface-model-first-return-dsm-1m/wcs",
            "df4e3ec3-315e-48aa-aaaf-b5ae74d7b2bb__Lidar_Composite_Elevation_FZ_DSM_1m"),
    "dtm": ("https://environment.data.gov.uk/spatialdata/lidar-composite-digital-terrain-model-dtm-1m/wcs",
            "13787b9a-26a4-4775-8523-806d13af58fc__Lidar_Composite_Elevation_DTM_1m"),
}


def get(url, dest, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=300) as r, open(dest, "wb") as f:
                f.write(r.read())
            with rasterio.open(dest) as d:        # a JSON error body is not a GeoTIFF
                d.read(1, window=((0, 1), (0, 1)))
            return
        except Exception as ex:                      # noqa: BLE001
            print(f"  retry {i + 1}: {ex}", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"gave up on {url}")


def fetch(kind):
    base, cid = WCS[kind]
    out = RAW / f"{kind}_{CELL}m.tif"
    if out.exists():
        print(out, "exists")
        return out
    tiles = RAW / f"tiles_{kind}"
    tiles.mkdir(parents=True, exist_ok=True)
    w, h = (E1 - E0) // CELL, (N1 - N0) // CELL
    mosaic = np.full((h, w), np.nan, dtype="float32")
    for e in range(E0, E1, TILE):
        for n in range(N0, N1, TILE):
            e2, n2 = min(e + TILE, E1), min(n + TILE, N1)
            dest = tiles / f"{kind}_{e}_{n}.tif"
            if not dest.exists():
                url = (f"{base}?service=WCS&version=2.0.1&request=GetCoverage&coverageId={cid}"
                       f"&format=image/tiff&subset=E({e},{e2})&subset=N({n},{n2})&scaleFactor={1 / CELL}")
                print(f"{kind} tile E{e} N{n}")
                get(url, dest)
            with rasterio.open(dest) as d:
                a = d.read(1).astype("float32")
                a[a == d.nodata] = np.nan
                a[a < -1e30] = np.nan
                r0 = (N1 - n2) // CELL
                c0 = (e - E0) // CELL
                mosaic[r0:r0 + a.shape[0], c0:c0 + a.shape[1]] = a[:h - r0, :w - c0]
    prof = dict(driver="GTiff", dtype="float32", count=1, width=w, height=h, crs="EPSG:27700",
                transform=from_origin(E0, N1, CELL, CELL), nodata=-9999.0, compress="deflate", tiled=True)
    with rasterio.open(out, "w", **prof) as d:
        d.write(np.where(np.isnan(mosaic), -9999.0, mosaic).astype("float32"), 1)
    print(out, mosaic.shape, "nan cells:", int(np.isnan(mosaic).sum()))
    return out


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    for kind in ("dsm", "dtm"):
        fetch(kind)
