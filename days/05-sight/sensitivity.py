"""Sensitivity checks for day 5, written into data/derived/stats.json["sensitivity"].

1. Open-ground threshold: the headline shares with objects under 1 m and 3 m counted as open ground, instead of 2 m.
2. Resolution: the same ray viewshed on the 1 m LiDAR for a 2 x 2 km square centred on the dome (every obstacle between
   an observer within 1 km and the dome lies inside the square), compared with the 5 m result on the same cells.
    python sensitivity.py
"""
import json, sys, time
from pathlib import Path
import numpy as np, rasterio
from rasterio.features import rasterize
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sight as S
from fetch_lidar import WCS, get

RAW, DER = S.RAW, S.DER
stats = json.loads((DER / "stats.json").read_text())
ax_x, ax_y = stats["dome_axis_bng"]; hg = stats["ground_m_aod"]
km2 = S.CELL ** 2 / 1e6
with rasterio.open(DER / "visible_level.tif") as d:
    lev = d.read(1); T = d.transform
with rasterio.open(RAW / "dsm_5m.tif") as d:          # the float nDSM, as in sight.viewshed (the stored one is rounded to 0.5 m)
    _dsm = d.read(1).astype("float64"); _dsm[_dsm == d.nodata] = np.nan
with rasterio.open(RAW / "dtm_5m.tif") as d:
    _dtm = d.read(1).astype("float64"); _dtm[_dtm == d.nodata] = np.nan
_dtm = np.where(np.isnan(_dtm), np.nanmedian(_dtm), _dtm)
_dsm = np.where(np.isnan(_dsm) | (_dsm < _dtm), _dtm, _dsm)
ndsm = _dsm - _dtm
fp, _ = S.stpauls_footprint()
body = rasterize([(fp.buffer(8), 1)], out_shape=lev.shape, transform=T, fill=0).astype(bool)
g = S.lvmf(); vc = g[(g.TYPE == "VC") & g.stpauls]
in_vc = rasterize([(geom, 1) for geom in vc.geometry], out_shape=lev.shape, transform=T, fill=0).astype(bool)
cls = np.where(lev == 255, 0, S.CLASS_OF_LEVEL[np.minimum(lev, 6)])
out = {"open_ground_threshold_m": {}, "resolution_1m_vs_5m_within_1km": {}}
for th in (1.0, 2.0, 3.0):
    og = (ndsm < th) & ~body
    sees = og & (cls > 0)
    out["open_ground_threshold_m"][str(th)] = dict(
        open_km2=round(og.sum() * km2, 1), sees_any_km2=round(sees.sum() * km2, 2),
        sees_any_share_of_open_pct=round(100 * sees.sum() / og.sum(), 2),
        vc_open_blind_pct=round(100 * (1 - (in_vc & sees).sum() / max((in_vc & og).sum(), 1)), 1),
        sees_any_outside_vc_pct=round(100 * (sees & ~in_vc).sum() / max(sees.sum(), 1), 1),
        whole_dome_km2=round((og & (cls == 3)).sum() * km2, 2))
    print(th, out["open_ground_threshold_m"][str(th)])

# ---- 1 m check on a 2 x 2 km square around the dome
tiles = RAW / "tiles_1m"; tiles.mkdir(exist_ok=True)
e0, n0 = int(ax_x) - 1000, int(ax_y) - 1000
arr = {}
for kind in ("dsm", "dtm"):
    f = tiles / f"{kind}_1m_dome.tif"
    if not f.exists():
        base, cid = WCS[kind]
        get(f"{base}?service=WCS&version=2.0.1&request=GetCoverage&coverageId={cid}&format=image/tiff"
            f"&subset=E({e0},{e0 + 2000})&subset=N({n0},{n0 + 2000})", f)
    with rasterio.open(f) as d:
        a = d.read(1).astype("float64"); a[(a == d.nodata) | (a < -1e30)] = np.nan
        arr[kind] = a; T1 = d.transform
dtm1 = np.where(np.isnan(arr["dtm"]), np.nanmedian(arr["dtm"]), arr["dtm"])
dsm1 = np.where(np.isnan(arr["dsm"]) | (arr["dsm"] < dtm1), dtm1, arr["dsm"])
body1 = rasterize([(fp.buffer(8), 1)], out_shape=dsm1.shape, transform=T1, fill=0).astype(bool)
obs1 = np.where(body1, dtm1, dsm1)
col1, row1 = ~T1 * (ax_x, ax_y)
t0 = time.time()
lev1 = S._rays(obs1, dtm1, float(col1), float(row1), hg, S.LEVELS, 1.0, S.EYE, 1500.0, S.K_REFR, S.R_EARTH)
print(f"1 m viewshed {time.time() - t0:.1f} s")
h1, w1 = lev1.shape
yy, xx = np.mgrid[0:h1, 0:w1]
d1 = np.hypot((xx - col1) * 1.0, (yy - row1) * 1.0)
og1 = ((dsm1 - dtm1) < S.OPEN_MAX) & ~body1 & (d1 < 1000)
cls1 = np.where(lev1 == 255, 0, S.CLASS_OF_LEVEL[np.minimum(lev1, 6)])
# the 5 m result on the same disc
c5, r5 = ~T * (ax_x, ax_y)
yy5, xx5 = np.mgrid[0:lev.shape[0], 0:lev.shape[1]]
d5 = np.hypot((xx5 - c5) * S.CELL, (yy5 - r5) * S.CELL)
og5 = (ndsm < S.OPEN_MAX) & ~body & (d5 < 1000)
out["resolution_1m_vs_5m_within_1km"] = {
    "5m": dict(open_km2=round(og5.sum() * km2, 3), sees_any_pct=round(100 * (og5 & (cls > 0)).sum() / og5.sum(), 1),
               whole_dome_pct=round(100 * (og5 & (cls == 3)).sum() / og5.sum(), 1)),
    "1m": dict(open_km2=round(og1.sum() / 1e6, 3), sees_any_pct=round(100 * (og1 & (cls1 > 0)).sum() / og1.sum(), 1),
               whole_dome_pct=round(100 * (og1 & (cls1 == 3)).sum() / og1.sum(), 1)),
    "note": "same ray method on the 1 m first-return DSM/DTM, 2 x 2 km square centred on the dome, observers within 1 km"}
print(out["resolution_1m_vs_5m_within_1km"])
stats["sensitivity"] = out
(DER / "stats.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False))
