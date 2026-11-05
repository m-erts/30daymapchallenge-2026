"""Day 5 of #30DayMapChallenge 2026, Senses: Sight. "What London is allowed to see."

The London View Management Framework (LVMF) protects a handful of view corridors towards
St Paul's Cathedral. This script puts those corridors over the view that actually exists:
from which open ground (streets, parks, the river) the dome is visible, by line of sight
across the Environment Agency LiDAR surface (buildings and trees), with earth curvature.

    python fetch_lidar.py            # DSM + DTM at 5 m (data/raw/, gitignored)
    python sight.py viewshed         # data/derived/visible_level.tif, ndsm_5m.tif, stats.json
    python sight.py figure en        # map_en_old.png, the dark version (ru -> map_ru_old.png); the main map: sight_os.py
    python sight.py all

Target: the vertical axis of the dome at 7 heights above the cathedral's ground level
(111 m top of the cross ... 25 m, below the peristyle). A cell's value is the lowest of those
heights it can see; the cathedral's own body is removed from the obstacle surface so that the
axis stands for the dome's silhouette. Eye height 1.6 m, refraction k = 0.13.
"""
from __future__ import annotations

import os
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import matplotlib as mpl
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from numba import njit
from rasterio.features import rasterize
from shapely.geometry import Point, shape

HERE = Path(__file__).resolve().parent
RAW, DER = HERE / "data" / "raw", HERE / "data" / "derived"
CELL = 5
EYE = 1.6                      # m, eye above ground
OPEN_MAX = 2.0                 # m, objects lower than this = open ground
LEVELS = np.array([111.0, 100.0, 85.0, 70.0, 53.0, 40.0, 25.0])   # m above the cathedral's ground
# display classes from the lowest visible level: index into LEVELS
CLASS_OF_LEVEL = np.array([1, 1, 2, 2, 3, 3, 3])   # 1 lantern & cross, 2 upper dome, 3 whole dome
K_REFR, R_EARTH = 0.13, 6_371_000.0
LVMF_ZIP = ("https://data.london.gov.uk/download/2yjmq/22779d63-01d6-4717-8fe8-b12b0bc0e136/"
            "Protected%20Vistas%20LVMF.zip")
LVMF_SHP = RAW / "lvmf" / "unz" / "Protected Vistas" / "Protected Vistas LVMF 2010_region.shp"
UA = {"User-Agent": "30DayMapChallenge-day5 (urban_mash; mercegovacm@gmail.com)"}

# palette: the series' DESIGN.md tokens (dark surface)
BG, FG, MUTED, BORDER, CARD = "#000000", "#EDEDED", "#888888", "#333333", "#0A0A0A"
BLUE, CYAN = "#0070F3", "#50E3C2"
CYANS = {3: "#50E3C2", 2: "#1FA58E", 1: "#0F6657"}      # whole dome, upper dome, lantern only
WATER = "#0B1A2B"
GREYS = ["#1C1C1C", "#4A4A4A"]                            # objects 2 m .. 30 m


# ----------------------------------------------------------------------------- inputs
def lvmf():
    if not LVMF_SHP.exists():
        LVMF_SHP.parents[2].mkdir(parents=True, exist_ok=True)
        z = LVMF_SHP.parents[2] / "lvmf.zip"
        with urllib.request.urlopen(LVMF_ZIP, timeout=120) as r, open(z, "wb") as f:
            f.write(r.read())
        zipfile.ZipFile(z).extractall(LVMF_SHP.parents[1])
    g = gpd.read_file(LVMF_SHP).to_crs(27700)
    g["place"] = g.DESCRIPTIO.str.split(" to ").str[0]
    g["landmark"] = g.DESCRIPTIO.str.split(" to ").str[-1]
    g["stpauls"] = g.landmark.str.contains("St Paul")
    return g


def stpauls_footprint():
    """OSM building footprint of St Paul's (way 369161987) via Nominatim, cached."""
    f = DER / "stpauls_osm.geojson"
    if not f.exists():
        url = ("https://nominatim.openstreetmap.org/search?q=St+Paul%27s+Cathedral,+London"
               "&format=jsonv2&polygon_geojson=1&limit=1")
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
            hit = json.load(r)[0]
        f.write_text(json.dumps(dict(type="Feature", properties=dict(osm_type=hit["osm_type"], osm_id=hit["osm_id"],
                                                                      licence=hit["licence"]), geometry=hit["geojson"])))
    feat = json.loads(f.read_text())
    return gpd.GeoSeries([shape(feat["geometry"])], crs=4326).to_crs(27700).iloc[0], feat["properties"]


def dome_axis(footprint):
    """Highest first-return LiDAR cell (1 m) inside the footprint = the lantern above the dome."""
    f = DER / "stpauls_dsm_1m.tif"
    if not f.exists():
        x0, y0, x1, y1 = [int(v) for v in footprint.bounds]
        url = ("https://environment.data.gov.uk/spatialdata/lidar-composite-digital-surface-model-first-return-dsm-1m/wcs"
               "?service=WCS&version=2.0.1&request=GetCoverage&format=image/tiff"
               "&coverageId=df4e3ec3-315e-48aa-aaaf-b5ae74d7b2bb__Lidar_Composite_Elevation_FZ_DSM_1m"
               f"&subset=E({x0 - 20},{x1 + 20})&subset=N({y0 - 20},{y1 + 20})")
        with urllib.request.urlopen(url, timeout=120) as r, open(f, "wb") as out:
            out.write(r.read())
    with rasterio.open(f) as d:
        a = d.read(1)
        inside = rasterize([(footprint, 1)], out_shape=a.shape, transform=d.transform, fill=0).astype(bool)
        a = np.where(inside, a, -1e9)
        r, c = np.unravel_index(np.argmax(a), a.shape)
        x, y = d.transform * (c + 0.5, r + 0.5)
        return float(x), float(y), float(a[r, c])


def water():
    """Overture Maps water polygons for the extent (Overture base theme, mostly OSM, ODbL)."""
    f = DER / "water.gpkg"
    if not f.exists():
        import duckdb
        from pyproj import Transformer
        with rasterio.open(RAW / "dtm_5m.tif") as d:
            b = d.bounds
        tr = Transformer.from_crs(27700, 4326, always_xy=True)
        xs, ys = zip(*[tr.transform(x, y) for x in (b.left, b.right) for y in (b.bottom, b.top)])
        s3 = "s3://overturemaps-us-west-2/release"
        duckdb.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET http_retries = 6; SET s3_region='us-west-2';")
        rel = max(p.split("/")[4] for p, in duckdb.sql(f"FROM glob('{s3}/*/theme=base/type=water/*')").fetchall())
        rows = duckdb.sql(f"""SELECT subtype, class, ST_AsText(geometry) AS wkt
            FROM read_parquet('{s3}/{rel}/theme=base/type=water/*', hive_partitioning=1)
            WHERE bbox.xmin <= {max(xs)} AND bbox.xmax >= {min(xs)} AND bbox.ymin <= {max(ys)} AND bbox.ymax >= {min(ys)}
              AND ST_GeometryType(geometry) IN ('POLYGON', 'MULTIPOLYGON')
              AND subtype IN ('river', 'canal', 'lake', 'reservoir', 'water', 'physical')""").fetchall()
        g = gpd.GeoDataFrame([dict(subtype=s, cls=c) for s, c, _ in rows],
                             geometry=gpd.GeoSeries.from_wkt([w for *_, w in rows], crs=4326)).to_crs(27700)
        g["release"] = rel
        g.to_file(f, driver="GPKG")
    return gpd.read_file(f)


# ----------------------------------------------------------------------------- viewshed
@njit(cache=True)
def _rays(obs, grd, cx, cy, hg, levels, cell, eye, rmax, k, R):
    """Lowest visible target level per cell, by rays from the dome axis outward.

    obs: obstacle surface (m AOD), grd: ground (m AOD). cx, cy: axis in array coords (col, row).
    Visible at level l when the slope from the target to the eye (ground + eye) is not below the
    running maximum slope to any obstacle top between them; heights are lowered by the curvature
    drop (1 - k) r^2 / 2R relative to the axis. Returns uint8: index into levels (lowest visible),
    255 where nothing of the target is seen."""
    h, w = obs.shape
    n_lev = levels.shape[0]
    out = np.full((h, w), 255, np.uint8)
    dr = 0.5 * cell
    n_rays = int(np.ceil(2.0 * np.pi * rmax / dr))
    n_steps = int(rmax / dr)
    maxs = np.empty(n_lev)
    for a in range(n_rays):
        th = 2.0 * np.pi * a / n_rays
        ct, st = np.cos(th), np.sin(th)
        for l in range(n_lev):
            maxs[l] = -1e9
        for s in range(1, n_steps):
            r = s * dr
            col = int(np.floor(cx + r * ct / cell))
            row = int(np.floor(cy - r * st / cell))
            if col < 0 or col >= w or row < 0 or row >= h:
                break
            drop = (1.0 - k) * r * r / (2.0 * R)
            z_ob = obs[row, col] - drop
            z_ey = grd[row, col] + eye - drop
            for l in range(n_lev):
                ht = hg + levels[l]
                if (z_ey - ht) / r >= maxs[l]:
                    if out[row, col] == 255 or l > out[row, col]:
                        out[row, col] = l
                sl = (z_ob - ht) / r
                if sl > maxs[l]:
                    maxs[l] = sl
    return out


def viewshed():
    DER.mkdir(parents=True, exist_ok=True)
    with rasterio.open(RAW / "dsm_5m.tif") as d:
        dsm = d.read(1).astype("float64")
        prof, T = d.profile, d.transform
        dsm[dsm == d.nodata] = np.nan
    with rasterio.open(RAW / "dtm_5m.tif") as d:
        dtm = d.read(1).astype("float64")
        dtm[dtm == d.nodata] = np.nan
    print("nodata cells dsm/dtm:", int(np.isnan(dsm).sum()), int(np.isnan(dtm).sum()))
    dtm = np.where(np.isnan(dtm), np.nanmedian(dtm), dtm)
    dsm = np.where(np.isnan(dsm) | (dsm < dtm), dtm, dsm)     # no object below its own ground

    fp, _ = stpauls_footprint()
    ax_x, ax_y, top = dome_axis(fp)
    col, row = ~T * (ax_x, ax_y)
    hg = float(dtm[int(row), int(col)])
    print(f"dome axis E {ax_x:.1f} N {ax_y:.1f}; LiDAR top {top:.1f} m AOD; ground {hg:.1f} m AOD; "
          f"offset from OSM centroid {fp.centroid.distance(Point(ax_x, ax_y)):.0f} m")
    # the cathedral itself is the target, not an obstacle: flatten it to the ground
    body = rasterize([(fp.buffer(8), 1)], out_shape=dsm.shape, transform=T, fill=0).astype(bool)
    obs = np.where(body, dtm, dsm)

    h, w = dsm.shape
    corners = [(0, 0), (0, w), (h, 0), (h, w)]
    rmax = max(np.hypot((c - col) * CELL, (r - row) * CELL) for r, c in corners) + 2 * CELL
    import time
    t0 = time.time()
    lev = _rays(obs, dtm, float(col), float(row), hg, LEVELS, float(CELL), EYE, float(rmax), K_REFR, R_EARTH)
    print(f"viewshed {time.time() - t0:.1f} s")

    ndsm = (dsm - dtm).astype("float32")
    open_ground = (ndsm < OPEN_MAX) & ~body
    prof.update(dtype="uint8", nodata=255, count=1)
    with rasterio.open(DER / "visible_level.tif", "w", **prof) as d:
        d.write(lev, 1)
    # objects above ground in half-metres (uint8, 0..127 m): enough for the open-ground mask and the grey ramp, ~3 MB
    with rasterio.open(DER / "ndsm_5m.tif", "w", **prof) as d:
        d.write(np.clip(np.round(ndsm * 2), 0, 254).astype("uint8"), 1)

    # ------------------------------------------------------------------ statistics
    cls = np.where(lev == 255, 0, CLASS_OF_LEVEL[np.minimum(lev, 6)])
    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.hypot((xx - col) * CELL, (yy - row) * CELL)
    km2 = CELL * CELL / 1e6
    g = lvmf()
    vc_sp = g[(g.TYPE == "VC") & g.stpauls]
    ws_sp = g[(g.TYPE == "WSCA") & g.stpauls]
    in_vc = rasterize([(geom, 1) for geom in vc_sp.geometry], out_shape=dsm.shape, transform=T, fill=0).astype(bool)
    in_ws = rasterize([(geom, 1) for geom in ws_sp.geometry], out_shape=dsm.shape, transform=T, fill=0).astype(bool)
    sees = open_ground & (cls > 0)
    whole = open_ground & (cls == 3)
    stats = dict(
        dome_axis_bng=[round(ax_x, 1), round(ax_y, 1)], lidar_top_m_aod=round(top, 1), ground_m_aod=round(hg, 1),
        levels_m_above_ground=LEVELS.tolist(), extent_bng=[T.c, T.f - h * CELL, T.c + w * CELL, T.f],
        open_ground_km2=round(open_ground.sum() * km2, 2),
        sees_any_km2=round(sees.sum() * km2, 2), sees_whole_dome_km2=round(whole.sum() * km2, 2),
        sees_any_within_10km_km2=round((sees & (dist < 10_000)).sum() * km2, 2),
        open_within_10km_km2=round((open_ground & (dist < 10_000)).sum() * km2, 2),
        vc_stpauls_km2=round(float(vc_sp.area.sum()) / 1e6, 2),
        vc_stpauls_open_km2=round((in_vc & open_ground).sum() * km2, 2),
        vc_stpauls_open_sees_any_km2=round((in_vc & sees).sum() * km2, 2),
        vc_stpauls_open_sees_whole_km2=round((in_vc & whole).sum() * km2, 2),
        sees_any_outside_vc_share=round(float((sees & ~in_vc).sum() / max(sees.sum(), 1)), 4),
        sees_any_outside_vc_and_wsca_share=round(float((sees & ~in_vc & ~in_ws).sum() / max(sees.sum(), 1)), 4),
        class_km2={"whole_dome": round((open_ground & (cls == 3)).sum() * km2, 2),
                   "upper_dome": round((open_ground & (cls == 2)).sum() * km2, 2),
                   "lantern_only": round((open_ground & (cls == 1)).sum() * km2, 2)},
        corridors=[], places=[])
    for _, v in vc_sp.iterrows():
        m = rasterize([(v.geometry, 1)], out_shape=dsm.shape, transform=T, fill=0).astype(bool)
        og = m & open_ground
        stats["corridors"].append(dict(view=v.VIEW, place=v.place, area_km2=round(v.geometry.area / 1e6, 3),
                                       open_share=round(float(og.sum() / max(m.sum(), 1)), 3),
                                       open_sees_any=round(float((og & sees).sum() / max(og.sum(), 1)), 3),
                                       open_sees_whole=round(float((og & whole).sum() / max(og.sum(), 1)), 3)))
    for _, v in places(g).iterrows():
        c, r = ~T * (v.geometry.x, v.geometry.y)
        c, r = int(c), int(r)
        win = (slice(max(r - 6, 0), r + 7), slice(max(c - 6, 0), c + 7))        # +-30 m
        here = int(lev[r, c])
        best = int(lev[win][open_ground[win]].max()) if open_ground[win].any() else 255   # max index = lowest level
        stats["places"].append(dict(place=v.place, landmark=v.landmark, bng=[round(v.geometry.x), round(v.geometry.y)],
                                    ground_m=round(float(dtm[r, c]), 1), object_height_m=round(float(ndsm[r, c]), 1),
                                    lowest_visible_level_here=None if here == 255 else float(LEVELS[here]),
                                    lowest_visible_level_within_30m=None if best == 255 else float(LEVELS[best])))
    checks = {"Millennium Bridge, south end": (532010, 180760), "Ludgate Circus (Fleet Street)": (531560, 181170),
              "Waterloo Bridge, middle": (530800, 180600), "Tate Modern riverside": (531950, 180600),
              "Thames off Blackfriars": (531700, 180750), "Cannon Street at Walbrook": (532560, 180960),
              "Paternoster Square": (532000, 181270), "Hungerford Bridge": (530420, 180310),
              "Tower Bridge, middle": (533620, 180330), "Canary Wharf, Cabot Square": (537560, 180330)}
    stats["checks"] = {}
    for name, (x, y) in checks.items():
        c, r = ~T * (x, y)
        v = int(lev[int(r), int(c)])
        stats["checks"][name] = dict(open_ground=bool(open_ground[int(r), int(c)]), object_m=round(float(ndsm[int(r), int(c)]), 1),
                                     lowest_visible_level=None if v == 255 else float(LEVELS[v]))
    (DER / "stats.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in stats.items() if k not in ("corridors", "places")}, indent=1))
    for c in stats["corridors"]:
        print(c)
    for p in stats["places"]:
        print(p)
    for k, v in stats["checks"].items():
        print(k, v)


def places(g):
    """Designated viewing places = the apex of each viewing corridor: the vertex farthest from
    St Paul's (every landmark in the set lies closer to St Paul's than its viewing place)."""
    fp, _ = stpauls_footprint()
    c = fp.centroid
    rows = []
    for _, v in g[g.TYPE == "VC"].iterrows():
        pts = [Point(p) for p in v.geometry.exterior.coords]
        far = max(pts, key=c.distance)
        near_far = [p for p in pts if p.distance(far) < 40]
        apex = Point(np.mean([p.x for p in near_far]), np.mean([p.y for p in near_far]))
        rows.append(dict(view=v.VIEW, place=v.place, landmark=v.landmark, stpauls=v.stpauls, geometry=apex))
    out = gpd.GeoDataFrame(rows, crs=27700)
    return out.drop_duplicates(subset=["place", "landmark"])


# ----------------------------------------------------------------------------- figure
T = {
    "en": dict(
        title="What London is allowed to see",
        sub=("Blue: the eight view corridors that the London View Management Framework protects\n"
             "for St Paul's Cathedral (grey: corridors to Westminster and the Tower). Cyan: where the\n"
             "dome is actually visible from street level, by line of sight across LiDAR buildings and trees."),
        stats=("Inside the protected corridors, {in_blind}% of the open ground never sees the dome: the law guards\n"
               "a line in the sky, not the streets beneath it. The dome is seen from {any} km² of streets, parks\n"
               "and river, {out}% of that outside any corridor; the whole dome from {whole} km²."),
        leg_title="Lowest part of the dome seen from open ground",
        leg=[(3, "whole dome, down to its base (53 m)"), (2, "upper dome (70–85 m)"), (1, "only the lantern and cross (100–111 m)")],
        leg_grey="buildings and trees (LiDAR surface)", leg_water="water", leg_vc="protected viewing corridor (LVMF)",
        leg_ws="wider setting consultation area", leg_pt="designated viewing place",
        places={"Alexandra Palace viewing terrace": "Alexandra Palace", "Parliament Hill summit": "Parliament Hill",
                "Parliament Hill oak tree": "", "Kenwood viewing gazebo": "Kenwood", "Primrose Hill summit": "Primrose Hill",
                "Greenwich Park Wolfe statue": "Greenwich Park", "Blackheath Point": "Blackheath Point",
                "Westminster Pier": "Westminster Pier", "King Henry's Mound": "King Henry's Mound,\nRichmond Park",
                "Centre of Bridge over the Serpentine": "Serpentine Bridge", "City Hall": "City Hall"},
        notes=[("thames", "River and South Bank see the whole dome.\nNo LVMF corridor: the City's own St Paul's\nHeights grid has kept these views since 1938."),
               ("corridor", "A corridor protects the view from\nthe summit; the streets under it\nmostly see roofs."),
               ("richmond", "16 km: the famous keyhole through\nthe hedge is thinner than 5 m LiDAR")],
        stpauls="St Paul's", km="km",
        src=("Data: GLA, LVMF protected vistas (SPG 2010; OGL v2) · Environment Agency LiDAR composite first-return DSM and DTM 1 m,\n"
             "flights 2016–2022 (OGL v3), resampled to 5 m · OpenStreetMap (St Paul's footprint) and Overture Maps (water), ODbL.\n"
             "Method: line of sight from a 1.6 m eye at ground level to the dome's axis at 7 heights (25–111 m above ground),\n"
             "earth curvature and refraction (k = 0.13); shown on open ground and water (objects under 2 m).\n"
             "Analysis: Marija Ercegovac · #30DayMapChallenge day 5")),
    "ru": dict(
        title="Что Лондону разрешено видеть",
        sub=("Синим: восемь коридоров видов, которые London View Management Framework охраняет для\n"
             "собора св. Павла (серым: коридоры к Вестминстеру и Тауэру). Бирюзовым: откуда купол\n"
             "действительно виден с уровня улицы по лучу зрения поверх зданий и деревьев из LiDAR."),
        stats=("Внутри охраняемых коридоров {in_blind}% открытой земли купола не видят: закон бережёт линию\n"
               "в небе, а не улицы под ней. Купол виден с {any} км² улиц, парков и реки, {out}% из них\n"
               "вне любого коридора; весь купол целиком с {whole} км²."),
        leg_title="Нижняя видимая часть купола с открытой земли",
        leg=[(3, "весь купол, до основания (53 м)"), (2, "верх купола (70–85 м)"), (1, "только фонарь и крест (100–111 м)")],
        leg_grey="здания и деревья (поверхность LiDAR)", leg_water="вода", leg_vc="охраняемый коридор вида (LVMF)",
        leg_ws="зона консультаций вокруг вида", leg_pt="назначенная точка обзора",
        places={"Alexandra Palace viewing terrace": "Александра-палас", "Parliament Hill summit": "Парламент-хилл",
                "Parliament Hill oak tree": "", "Kenwood viewing gazebo": "Кенвуд", "Primrose Hill summit": "Примроуз-хилл",
                "Greenwich Park Wolfe statue": "Гринвич-парк", "Blackheath Point": "Блэкхит-пойнт",
                "Westminster Pier": "Вестминстерский пирс", "King Henry's Mound": "Холм Генриха VIII,\nРичмонд-парк",
                "Centre of Bridge over the Serpentine": "Мост через Серпентайн", "City Hall": "Сити-холл"},
        notes=[("thames", "С реки и Саут-Бэнка виден весь купол.\nКоридора LVMF тут нет: эти виды с 1938 года\nдержит сетка высот St Paul's Heights Сити."),
               ("corridor", "Коридор охраняет вид с вершины;\nулицы под ним в основном видят\nкрыши."),
               ("richmond", "16 км: знаменитая «замочная скважина»\nв живой изгороди тоньше 5 м LiDAR")],
        stpauls="Собор св. Павла", km="км",
        src=("Данные: GLA, LVMF protected vistas (SPG 2010; OGL v2) · Environment Agency, LiDAR-композиты DSM (первое отражение) и DTM 1 м,\n"
             "съёмка 2016–2022 (OGL v3), пересчёт в 5 м · OpenStreetMap (контур собора) и Overture Maps (вода), ODbL.\n"
             "Метод: луч зрения от глаза на высоте 1,6 м над землёй к оси купола на 7 высотах (25–111 м над землёй),\n"
             "кривизна Земли и рефракция (k = 0,13); показано на открытой земле и воде (объекты ниже 2 м).\n"
             "Расчёт: Мария Эрцеговац · #30DayMapChallenge день 5")),
}
# label offsets (m east, m north, ha) per viewing place, tuned by eye on the rendered map
OFFSETS = {"Alexandra Palace viewing terrace": (400, -300, "left"), "Parliament Hill summit": (-400, 300, "right"),
           "Kenwood viewing gazebo": (-400, 200, "right"), "Primrose Hill summit": (-400, 0, "right"),
           "Greenwich Park Wolfe statue": (-450, 350, "right"), "Blackheath Point": (-450, -350, "right"),
           "Westminster Pier": (-400, -350, "right"), "King Henry's Mound": (700, 1050, "left"),
           "Centre of Bridge over the Serpentine": (-400, 300, "right"), "City Hall": (450, -350, "left")}
# callout anchors (text position, arrow target), BNG
NOTES = {"thames": ((531600, 178750), (533000, 180400)), "corridor": ((518800, 185200), (528800, 184840)),
         "richmond": ((523300, 173650), (518900, 173400))}


def setup_fonts():
    fonts = sorted(Path(os.environ.get("GEIST_FONTS", Path(__file__).resolve().parents[3] / "belgrade-green/data/cache/fonts")).glob("Geist-*.ttf"))
    fonts = [f for f in fonts if "Variable" not in f.name]
    for f in fonts:
        fm.fontManager.addfont(str(f))
    mpl.rcParams.update({"font.family": "Geist" if fonts else "Helvetica Neue", "text.color": FG,
                         "figure.facecolor": BG, "savefig.facecolor": BG, "axes.facecolor": BG})


def fmt(x, lang, nd=0):
    s = f"{x:.{nd}f}"
    return s.replace(".", ",") if lang == "ru" else s


def figure(lang="en"):
    setup_fonts()
    t = T[lang]
    stats = json.loads((DER / "stats.json").read_text())
    with rasterio.open(DER / "visible_level.tif") as d:
        lev = d.read(1)
        Tr, b = d.transform, d.bounds
    with rasterio.open(DER / "ndsm_5m.tif") as d:
        ndsm = d.read(1).astype("float32") / 2          # half-metres -> metres
    g = lvmf()
    fp, _ = stpauls_footprint()
    ax_x, ax_y = stats["dome_axis_bng"]
    wat = water()
    water_mask = rasterize([(geom, 1) for geom in wat.geometry], out_shape=lev.shape, transform=Tr, fill=0).astype(bool)
    body = rasterize([(fp.buffer(8), 1)], out_shape=lev.shape, transform=Tr, fill=0).astype(bool)

    # RGB image: objects grey by height, open ground dark, water blue-black, visible cells cyan by class
    cls = np.where(lev == 255, 0, CLASS_OF_LEVEL[np.minimum(lev, 6)])
    open_ground = (ndsm < OPEN_MAX) & ~body
    rgb = np.empty(lev.shape + (3,), dtype="float32")
    rgb[:] = mpl.colors.to_rgb(CARD)
    grey = mpl.colors.LinearSegmentedColormap.from_list("g", GREYS)
    obj = ~open_ground
    rgb[obj] = grey(np.clip((ndsm[obj] - 2) / 28, 0, 1))[:, :3]
    rgb[water_mask & open_ground] = mpl.colors.to_rgb(WATER)
    for k, c in CYANS.items():
        rgb[open_ground & (cls == k)] = mpl.colors.to_rgb(c)
    rgb[body] = mpl.colors.to_rgb(FG)

    W, H = 5.4, 6.75
    fig = plt.figure(figsize=(W, H), dpi=300)
    mx0, my0, mw, mh = 0.0, 0.168, 1.0, 0.632          # map box; extent cropped to its aspect
    ext_w = b.right - b.left
    ext_h = ext_w / ((mw * W) / (mh * H))
    cy = (b.top + b.bottom) / 2
    y0, y1 = cy - ext_h / 2, cy + ext_h / 2
    ax = fig.add_axes([mx0, my0, mw, mh])
    ax.set_xlim(b.left, b.right)
    ax.set_ylim(y0, y1)
    ax.set_axis_off()
    ax.imshow(rgb, extent=(b.left, b.right, b.bottom, b.top), interpolation="antialiased", zorder=1)

    other = g[~g.stpauls]
    other[other.TYPE == "VC"].boundary.plot(ax=ax, color=MUTED, linewidth=0.45, zorder=3, alpha=0.9)
    other[other.TYPE == "WSCA"].boundary.plot(ax=ax, color=MUTED, linewidth=0.3, linestyle=(0, (2, 2)), zorder=3, alpha=0.6)
    sp = g[g.stpauls]
    sp[sp.TYPE == "WSCA"].boundary.plot(ax=ax, color=BLUE, linewidth=0.35, linestyle=(0, (2, 2)), zorder=4, alpha=0.8)
    sp[sp.TYPE == "VC"].plot(ax=ax, facecolor=mpl.colors.to_rgba(BLUE, 0.28), edgecolor=BLUE, linewidth=0.6, zorder=5)

    halo = dict(boxstyle="square,pad=0.12", facecolor=BG, edgecolor="none", alpha=0.72)
    # viewing places: one marker per place, white if it looks at St Paul's
    pl = places(g).sort_values("stpauls", ascending=False).drop_duplicates(subset="place")
    for _, v in pl.iterrows():
        name = t["places"].get(v.place, v.place)
        col = FG if v.stpauls else MUTED
        ax.scatter([v.geometry.x], [v.geometry.y], s=11, facecolor=col, edgecolor=BG, linewidth=0.5, zorder=8)
        if not name:
            continue
        dx, dy, ha = OFFSETS.get(v.place, (300, 300, "left"))
        ax.annotate(name, (v.geometry.x, v.geometry.y), (v.geometry.x + dx, v.geometry.y + dy), ha=ha, va="center",
                    fontsize=6.2, color=col, zorder=9, bbox=halo, linespacing=1.15,
                    arrowprops=dict(arrowstyle="-", color=col, lw=0.4, shrinkA=0, shrinkB=2))
    ax.scatter([ax_x], [ax_y], s=46, facecolor="none", edgecolor=CYAN, linewidth=0.9, zorder=9)
    ax.annotate(t["stpauls"], (ax_x, ax_y), (ax_x + 500, ax_y + 700), ha="left", va="center", fontsize=6.8,
                color=FG, fontweight="semibold", zorder=9, bbox=halo,
                arrowprops=dict(arrowstyle="-", color=FG, lw=0.5, shrinkA=0, shrinkB=4))
    # callouts
    for key, text in t["notes"]:
        (tx, ty), (px, py) = NOTES[key]
        ax.annotate(text, (px, py), (tx, ty), ha="left", va="center", fontsize=5.6, color="#CFCFCF", zorder=10,
                    linespacing=1.3, bbox=dict(boxstyle="square,pad=0.3", facecolor=BG, edgecolor=BORDER, linewidth=0.4, alpha=0.9),
                    arrowprops=dict(arrowstyle="-", color="#CFCFCF", lw=0.45, shrinkA=0, shrinkB=0))

    # scale bar: 5 km, bottom right
    sx, sy = b.right - 900 - 5000, y0 + 650
    ax.plot([sx, sx + 5000], [sy, sy], color=FG, lw=1.0, solid_capstyle="butt", zorder=9)
    for xv in (sx, sx + 5000):
        ax.plot([xv, xv], [sy - 90, sy + 90], color=FG, lw=0.8, zorder=9)
    ax.text(sx + 2500, sy + 170, f"5 {t['km']}", ha="center", va="bottom", fontsize=6, color=FG, zorder=9)

    # title block
    in_blind = 100 * (1 - stats["vc_stpauls_open_sees_any_km2"] / stats["vc_stpauls_open_km2"])
    fig.text(0.045, 0.965, t["title"], fontsize=15.5, fontweight="semibold", color=FG, va="top", ha="left")
    fig.text(0.045, 0.918, t["sub"], fontsize=6.7, color="#BBBBBB", va="top", ha="left", linespacing=1.45)
    fig.text(0.045, 0.857, t["stats"].format(in_blind=fmt(in_blind, lang), any=fmt(stats["sees_any_km2"], lang, 1),
                                             out=fmt(100 * stats["sees_any_outside_vc_share"], lang),
                                             whole=fmt(stats["sees_whole_dome_km2"], lang, 1)),
             fontsize=6.7, color=CYAN, va="top", ha="left", linespacing=1.45)

    # legend (two columns) above the caption
    handles = [Patch(facecolor=CYANS[k], edgecolor="none", label=lab) for k, lab in t["leg"]]
    handles += [Patch(facecolor=GREYS[1], edgecolor="none", label=t["leg_grey"]),
                Patch(facecolor=WATER, edgecolor=BORDER, linewidth=0.4, label=t["leg_water"]),
                Patch(facecolor=mpl.colors.to_rgba(BLUE, 0.28), edgecolor=BLUE, linewidth=0.6, label=t["leg_vc"]),
                Line2D([], [], color=BLUE, lw=0.5, linestyle=(0, (2, 2)), label=t["leg_ws"]),
                Line2D([], [], marker="o", color="none", markerfacecolor=FG, markeredgecolor=BG, markersize=3.4, label=t["leg_pt"])]
    leg = fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.034, 0.158), ncol=2, frameon=False,
                     fontsize=5.8, handlelength=1.6, handleheight=0.85, columnspacing=1.4, labelspacing=0.5,
                     title=t["leg_title"], title_fontsize=6.0, alignment="left", borderaxespad=0)
    leg.get_title().set_color("#BBBBBB")
    for txt in leg.get_texts():
        txt.set_color(FG)
    fig.text(0.045, 0.012, t["src"], fontsize=4.5, color=MUTED, va="bottom", ha="left", linespacing=1.4)
    out = HERE / f"map_{lang}_old.png"          # the original dark DESIGN.md version; the London sheet is made by sight_os.py
    fig.savefig(out, dpi=300)
    plt.close(fig)
    print(out)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("viewshed", "all"):
        viewshed()
    if cmd in ("figure", "all"):
        for lang in (sys.argv[2:] or ["en", "ru"]):
            figure(lang)
