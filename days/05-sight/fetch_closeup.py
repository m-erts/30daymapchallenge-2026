"""1 m LiDAR (EA composite DSM first return and DTM, OGL v3) for the 3D close-up of the video: St Paul's, the City and
the river, 3.2 x 2 km. Same WCS as fetch_lidar.py, native 1 m (no server-side resampling).

    python fetch_closeup.py      # data/raw/closeup_dsm_1m.tif, data/raw/closeup_dtm_1m.tif
"""
import numpy as np
import rasterio
from rasterio.transform import from_origin

import fetch_lidar as FL

E0, E1, N0, N1 = 530400, 533600, 180200, 182200
TILE = 1000

for kind in ("dsm", "dtm"):
    base, cid = FL.WCS[kind]
    out = FL.RAW / f"closeup_{kind}_1m.tif"
    if out.exists():
        print(out, "exists")
        continue
    tiles = FL.RAW / f"tiles_closeup_{kind}"
    tiles.mkdir(parents=True, exist_ok=True)
    w, h = E1 - E0, N1 - N0
    mosaic = np.full((h, w), np.nan, dtype="float32")
    for e in range(E0, E1, TILE):
        for n in range(N0, N1, TILE):
            e2, n2 = min(e + TILE, E1), min(n + TILE, N1)
            dest = tiles / f"{kind}_{e}_{n}.tif"
            if not dest.exists():
                FL.get(f"{base}?service=WCS&version=2.0.1&request=GetCoverage&coverageId={cid}"
                       f"&format=image/tiff&subset=E({e},{e2})&subset=N({n},{n2})", dest)
            with rasterio.open(dest) as d:
                a = d.read(1).astype("float32")
                a[(a == d.nodata) | (a < -1e30)] = np.nan
            r0, c0 = N1 - n2, e - E0
            mosaic[r0:r0 + a.shape[0], c0:c0 + a.shape[1]] = a[:h - r0, :w - c0]
    prof = dict(driver="GTiff", dtype="float32", count=1, width=w, height=h, crs="EPSG:27700", transform=from_origin(E0, N1, 1, 1),
                nodata=-9999.0, compress="deflate", tiled=True)
    with rasterio.open(out, "w", **prof) as d:
        d.write(np.where(np.isnan(mosaic), -9999.0, mosaic), 1)
    print(out, mosaic.shape, "nan:", int(np.isnan(mosaic).sum()))
