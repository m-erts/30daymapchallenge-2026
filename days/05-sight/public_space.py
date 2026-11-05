"""Denominator check for day 5: the same visibility measured on public space only (streets, pavements, footpaths,
squares and parks from Overture Maps) instead of all open ground (every 5 m cell whose LiDAR objects are under 2 m,
which also takes in private gardens, rail land and the water surface).

    python fetch_public_space.py      # once
    python public_space.py            # adds "public_space" to data/derived/stats.json and paris/data/derived/stats.json

Also exports the shared helpers used by the comparison, the zooms, the video and the web page:
    london_open(), share_grid(), public_mask()
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "paris"))
import sight as L  # noqa: E402

# half-widths (m) of the paved public strip by road class; footpaths are thinner than a cell, so all_touched rasterising
HALF_WIDTH = dict(motorway=10, trunk=9, primary=8, secondary=7, tertiary=6, residential=4.5, living_street=3.5,
                  unclassified=4, service=3, pedestrian=4, footway=1.5, sidewalk=1.5, crosswalk=2, steps=1.5, path=1.5,
                  cycleway=1.5, bridleway=1.5)
KM2 = L.CELL * L.CELL / 1e6
# overview aggregation: 50 m blocks of 5 m cells; colour = share of the block's open ground that sees the dome
BLOCK, MIN_OPEN = 10, 4
SHARE_EDGES = [0.10, 0.25, 0.50]
SHARE_COLOURS = ["#93B3D2", "#5F8BBB", "#2F5E94", "#173E6E"]     # (0,10%], (10,25%], (25,50%], (50,100%]
# overview encoding after the review (Masha, 04.11.2026): lightness = the best part of the dome seen anywhere in the 50 m cell
# (the three classes of the 5 m maps), saturation = the share of the cell's open ground that sees any part of it
SAT_EDGES = [0.10, 0.50]                                       # (0,10%], (10,50%], (50,100%]
LIGHT = {3: 0.27, 2: 0.46, 1: 0.67}                            # whole dome, upper dome, lantern only
SAT = [0.06, 0.28, 0.52]                                        # the Apur blues sit at 0.30-0.55
HUE = 0.59                                                      # Apur blue
# zoom windows for the 5 m detail (3640 x 2000 m): St Paul's and the river bend; the Sacré-Cœur and the La Chapelle rail yards
ZOOMS = {"london": (530080, 179900, 533720, 181900), "paris": (650804.8, 6864984.8, 654444.8, 6866984.8)}


def london_open():
    """Open ground exactly as sight.viewshed defines it (float nDSM < 2 m, cathedral body excluded), and the grid."""
    with rasterio.open(L.RAW / "dsm_5m.tif") as d:
        dsm = d.read(1).astype("float64"); dsm[dsm == d.nodata] = np.nan
        T = d.transform
    with rasterio.open(L.RAW / "dtm_5m.tif") as d:
        dtm = d.read(1).astype("float64"); dtm[dtm == d.nodata] = np.nan
    dtm = np.where(np.isnan(dtm), np.nanmedian(dtm), dtm)
    dsm = np.where(np.isnan(dsm) | (dsm < dtm), dtm, dsm)
    fp, _ = L.stpauls_footprint()
    body = rasterize([(fp.buffer(8), 1)], out_shape=dsm.shape, transform=T, fill=0).astype(bool)
    return ((dsm - dtm) < L.OPEN_MAX) & ~body, T, dsm, dtm, body


def public_mask(gpkg, shape, T, open_ground, water_mask):
    roads = gpd.read_file(gpkg, layer="roads")
    roads = roads[~roads.tunnel.astype(bool)]
    polys = roads.geometry.buffer(roads["class"].map(HALF_WIDTH).fillna(3).values, cap_style="flat")
    areas = gpd.read_file(gpkg, layer="areas")
    m_roads = rasterize([(g, 1) for g in polys], out_shape=shape, transform=T, fill=0, all_touched=True).astype(bool)
    m_areas = rasterize([(g, 1) for g in areas.geometry], out_shape=shape, transform=T, fill=0).astype(bool)
    return (m_roads | m_areas) & open_ground & ~water_mask, m_roads, m_areas


def share_grid(lev, open_ground, block=10, min_open=4):
    """Share of each block's open ground that sees the dome (any level); NaN where the block holds fewer than
    min_open open cells. Blocks are aggregated, never interpolated."""
    h, w = (lev.shape[0] // block) * block, (lev.shape[1] // block) * block
    sees = ((lev != 255) & open_ground)[:h, :w].reshape(h // block, block, w // block, block).sum(axis=(1, 3))
    opn = open_ground[:h, :w].reshape(h // block, block, w // block, block).sum(axis=(1, 3))
    share = np.where(opn >= min_open, sees / np.maximum(opn, 1), np.nan)
    return share, (h, w)


def share_rgba(lev, open_ground, transform):
    """RGBA image of the 50 m share classes and its extent (left, right, bottom, top) in the grid's CRS."""
    import matplotlib as mpl
    share, (h, w) = share_grid(lev, open_ground, BLOCK, MIN_OPEN)
    k = np.digitize(np.nan_to_num(share, nan=0), SHARE_EDGES, right=True)      # 0: (0,10%], ... 3: (50,100%]
    rgba = np.zeros(share.shape + (4,), dtype="float32")
    for i, c in enumerate(SHARE_COLOURS):
        rgba[(share > 0) & (k == i)] = (*mpl.colors.to_rgb(c), 1.0)
    left, top = transform.c, transform.f
    cell = transform.a
    return rgba, (left, left + w * cell, top - h * cell, top), share


def class_share_colours():
    """{(class, share bin): rgb}. The most saturated column doubles as the 5 m class colours (VIS), so a 5 m cell and a
    50 m cell that mostly sees the same part of the dome get the same blue."""
    import colorsys
    return {(k, j): colorsys.hls_to_rgb(HUE, light, s) for k, light in LIGHT.items() for j, s in enumerate(SAT)}


def best_class_grid(lev, open_ground, block=BLOCK):
    """Best part of the dome (3 whole, 2 upper, 1 lantern, 0 none) seen from any open cell of each block."""
    cls = np.where((lev != 255) & open_ground, L.CLASS_OF_LEVEL[np.minimum(lev, 6)], 0)
    h, w = (lev.shape[0] // block) * block, (lev.shape[1] // block) * block
    return cls[:h, :w].reshape(h // block, block, w // block, block).max(axis=(1, 3))


def class_share_rgba(lev, open_ground, transform):
    """RGBA image of the 50 m overview: colour by the best part seen in the cell, saturation by the share of its open
    ground that sees the dome; extent (left, right, bottom, top) in the grid's CRS."""
    share, (h, w) = share_grid(lev, open_ground, BLOCK, MIN_OPEN)
    best = best_class_grid(lev, open_ground, BLOCK)
    j = np.digitize(np.nan_to_num(share, nan=0), SAT_EDGES, right=True)
    rgba = np.zeros(share.shape + (4,), dtype="float32")
    for (k, jj), c in class_share_colours().items():
        rgba[(share > 0) & (best == k) & (j == jj)] = (*c, 1.0)
    left, top, cell = transform.c, transform.f, transform.a
    return rgba, (left, left + w * cell, top - h * cell, top), share, best


def summarise(lev, open_ground, public, zone, water_mask):
    sees = (lev != 255)
    cls = np.where(lev == 255, 0, L.CLASS_OF_LEVEL[np.minimum(lev, 6)])
    out = dict(
        public_km2=round(public.sum() * KM2, 2),
        public_share_of_open=round(float(public.sum() / open_ground.sum()), 4),
        public_sees_any_km2=round((public & sees).sum() * KM2, 2),
        public_sees_any_share=round(float((public & sees).sum() / public.sum()), 4),
        public_sees_whole_km2=round((public & (cls == 3)).sum() * KM2, 2),
        public_seeing_outside_zone_share=round(float((public & sees & ~zone).sum() / max((public & sees).sum(), 1)), 4),
        public_in_zone_km2=round((public & zone).sum() * KM2, 3),
        public_in_zone_blind_share=round(float(1 - (public & zone & sees).sum() / max((public & zone).sum(), 1)), 4),
        open_seeing_on_water_share=round(float((open_ground & sees & water_mask).sum() / max((open_ground & sees).sum(), 1)), 4),
        open_seeing_public_share=round(float((public & sees).sum() / max((open_ground & sees).sum(), 1)), 4),
    )
    return out


def run_london():
    open_ground, T, *_ = london_open()
    with rasterio.open(L.DER / "visible_level.tif") as d:
        lev = d.read(1)
    water_mask = rasterize([(g, 1) for g in L.water().geometry], out_shape=lev.shape, transform=T, fill=0).astype(bool)
    g = L.lvmf()
    zone = rasterize([(geom, 1) for geom in g[(g.TYPE == "VC") & g.stpauls].geometry], out_shape=lev.shape, transform=T, fill=0).astype(bool)
    public, m_roads, m_areas = public_mask(L.RAW / "public_london.gpkg", lev.shape, T, open_ground, water_mask)
    out = summarise(lev, open_ground, public, zone, water_mask)
    # per corridor: street-level public cells inside each St Paul's viewing corridor, and those of them that see the dome
    axx, ayy = json.loads((L.DER / "stats.json").read_text())["dome_axis_bng"]
    h, w = lev.shape
    yy, xx = np.mgrid[0:h, 0:w]
    xs, ys = T * (xx + 0.5, yy + 0.5)
    dist = np.hypot(xs - axx, ys - ayy)
    out["corridors"] = {}
    for _, v in g[(g.TYPE == "VC") & g.stpauls].iterrows():
        m = rasterize([(v.geometry, 1)], out_shape=lev.shape, transform=T, fill=0).astype(bool) & public
        band = m & (dist > 3000) & (dist < 5000)
        out["corridors"][v.VIEW] = dict(place=v.DESCRIPTIO.split(" to ")[0], public_cells=int(m.sum()), seeing=int((m & (lev != 255)).sum()),
                                        public_cells_3_5km=int(band.sum()), seeing_3_5km=int((band & (lev != 255)).sum()))
    out.update(note="public space = Overture road/footway/pedestrian segments buffered by class (tunnels dropped) + parks, gardens, "
                    "playgrounds, commons, plazas; intersected with open ground, water excluded (bridge decks stay: the EA DTM keeps them)",
               roads_cells_km2=round(m_roads.sum() * KM2, 2), areas_cells_km2=round(m_areas.sum() * KM2, 2))
    st = json.loads((L.DER / "stats.json").read_text())
    st["public_space"] = out
    (L.DER / "stats.json").write_text(json.dumps(st, indent=1, ensure_ascii=False))
    np.save(L.DER / "public_mask.npy", np.packbits(public))
    print("london", json.dumps(out, ensure_ascii=False))


def run_paris():
    import paris as P0
    stats, levs, ndsm, T, b, water_mask, bodies, body_any, open_ground = P0.load_paris()
    g = P0.fuseaux()
    public, m_roads, m_areas = public_mask(P0.RAW / "public_paris.gpkg", ndsm.shape, T, open_ground, water_mask)
    deck_public = open_ground & water_mask                      # bridge decks over water are open ground in the Paris model
    public |= deck_public & rasterize([(gg, 1) for gg in gpd.read_file(P0.RAW / "public_paris.gpkg", layer="roads").geometry.buffer(6)],
                                      out_shape=ndsm.shape, transform=T, fill=0, all_touched=True).astype(bool)
    out = {}
    for key in ("sacrecoeur", "pantheon"):
        zone = rasterize([(geom, 1) for geom in g[g.fuseau == P0.DOMES[key]["letter"]].geometry], out_shape=ndsm.shape, transform=T,
                         fill=0).astype(bool)
        out[key] = summarise(levs[key], open_ground, public, zone, water_mask)
    paris_city = rasterize([(P0.paris_boundary(), 1)], out_shape=ndsm.shape, transform=T, fill=0).astype(bool)
    lev = levs["sacrecoeur"]
    out["sacrecoeur"]["public_seeing_outside_paris_share"] = round(float((public & (lev != 255) & ~paris_city).sum() /
                                                                          max((public & (lev != 255)).sum(), 1)), 4)
    out["note"] = ("public space = Overture road/footway/pedestrian segments buffered by class (tunnels dropped) + parks, gardens, "
                   "playgrounds, commons, plazas; intersected with open ground (bridge decks included), water excluded")
    out["roads_cells_km2"], out["areas_cells_km2"] = round(m_roads.sum() * KM2, 2), round(m_areas.sum() * KM2, 2)
    stats["public_space"] = out
    (P0.DER / "stats.json").write_text(json.dumps(stats, indent=1, ensure_ascii=False))
    np.save(P0.DER / "public_mask.npy", np.packbits(public))
    print("paris", json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    for c in (sys.argv[1:] or ["london", "paris"]):
        {"london": run_london, "paris": run_paris}[c]()
