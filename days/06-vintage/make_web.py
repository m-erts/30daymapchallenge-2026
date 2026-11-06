"""Day 6: data for the interactive page (index.html): today's buildings with what stood on their spot in
May 1940, water, the brandgrens, buildings lost in 1940 (Wikidata), and the official map of the destroyed
area of May 1940, warped onto the web map.

    python make_web.py     # after fetch_data.py, build_brandgrens.py and make_map.py
                           # writes web/*.js, web/map1940.webp and the single-file rotterdam-1940.html

The 1940 map: Stadsarchief Rotterdam, archive 4001, I-210-1A, "Plattegrond van het middendeel van Rotterdam
met aanduiding van het gebied dat is verwoest door het bombardement van 14 mei 1940 en de daarop volgende
brand", 1:5000, Public Domain Mark 1.0 (https://hdl.handle.net/21.12133/CDD9C7CDDCEC43769E8D474193186EF5).
The image comes from the IIIF server of the Rotterdam Time Machine project (sammeltassen.nl) at a quarter of
its full size; the georeference is their Allmaps annotation (4 control points, affine), saved in
data/raw/map1940/. The warp is done here once, so the page needs no image server and no Allmaps runtime.

What stood on each spot in May 1940 is read off that map at the building's representative point:
orange = "verwoest gebied" (destroyed); a white hole inside the orange area = a building the city marked as
repairable or undamaged; anything else = outside the destroyed area. The georeference has 4 control points,
so near the edges of blocks the reading can be off by a building.

Data files are JavaScript (window.D6 = {...}) so that index.html also opens from disk, without a server.
rotterdam-1940.html carries everything inline (data, the 1940 image, Leaflet) for sending as one file.
"""
from __future__ import annotations

import base64
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
from PIL import Image, ImageDraw
from pyproj import Transformer
from scipy import ndimage as ndi
from shapely.geometry import Point, box, mapping
from shapely.ops import unary_union
from skimage.color import rgb2lab

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
DATA = HERE / "data"
WEB = HERE / "web"
M40 = RAW / "map1940"
VENDOR = RAW / "vendor"
IIIF = "https://sammeltassen.nl/iiif-images/stadsarchief-rotterdam/NL-RtSA_4001_I-210-1A-01"
ANNOTATION = "https://annotations.allmaps.org/images/438842f3998a5f05"
LEAFLET = "https://unpkg.com/leaflet@1.9.4/dist/"
IMG_WIDTH = 3626                     # one of the sizes the level-0 IIIF server offers
X0, X1, Y0, Y1 = 91300, 95400, 435500, 438900   # RD New, a bit wider than the static map
STANDING = ["Pand in gebruik", "Pand in gebruik (niet ingemeten)", "Verbouwing pand",
            "Pand buiten gebruik", "Sloopvergunning verleend"]
CELL = 3.0                           # Web Mercator units per pixel of the warped 1940 map (~1.9 m on the ground)
USES = {"woonfunctie": "homes", "winkelfunctie": "shops", "kantoorfunctie": "offices",
        "bijeenkomstfunctie": "gathering", "industriefunctie": "industry", "onderwijsfunctie": "education",
        "gezondheidszorgfunctie": "health care", "logiesfunctie": "lodging", "sportfunctie": "sport",
        "celfunctie": "detention", "overige gebruiksfunctie": "other"}
# Wikidata classes (Dutch labels) that are buildings; streets, squares, bridges and canals are left out
LOST_TYPES = {"bioscoop": "cinema", "kerkgebouw": "church", "vernielde kerk": "church", "synagoge": "synagogue",
              "theatergebouw": "theatre", "ziekenhuis": "hospital", "voormalig ziekenhuis": "hospital",
              "concertgebouw": "concert hall", "hotel": "hotel", "café": "café", "restaurant": "restaurant",
              "discotheek": "dance hall", "korpszaal": "Salvation Army hall", "museumgebouw": "museum",
              "woonhuis": "house", "gebouw": "building", "voormalig bouwwerk": "building",
              "evenementenlocatie": "venue"}

# Wikidata items with a 1940 end date that still stand: kept off the list of lost buildings
NOT_LOST = {"Q922407": "Laurenskerk: burned and restored; the end date on Wikidata marks the fire, not a demolition"}

to_wgs = Transformer.from_crs(28992, 4326, always_xy=True)
rd_to_merc = Transformer.from_crs(28992, 3857, always_xy=True)
wgs_to_merc = Transformer.from_crs(4326, 3857, always_xy=True)
merc_to_wgs = Transformer.from_crs(3857, 4326, always_xy=True)


# --- the 1940 map -----------------------------------------------------------------------------------

def fetch_1940():
    M40.mkdir(parents=True, exist_ok=True)
    img = M40 / f"NL-RtSA_4001_I-210-1A-01_{IMG_WIDTH}.jpg"
    ann = M40 / "allmaps_438842f3998a5f05.json"
    if not img.exists():
        r = requests.get(f"{IIIF}/full/{IMG_WIDTH},/0/default.jpg", timeout=120)
        r.raise_for_status()
        img.write_bytes(r.content)
    if not ann.exists():
        r = requests.get(ANNOTATION, timeout=60)
        r.raise_for_status()
        ann.write_bytes(r.content)
    return img, json.loads(ann.read_text())


def georef_1940():
    """Image, sheet mask and the affine mercator -> image pixel from the Allmaps annotation."""
    img_path, ann = fetch_1940()
    item = ann["items"][0]
    s = IMG_WIDTH / item["target"]["source"]["width"]
    gcps = item["body"]["features"]
    res = np.array([f["properties"]["resourceCoords"] for f in gcps], float) * s
    lon, lat = np.array([f["geometry"]["coordinates"] for f in gcps], float).T
    mx, my = wgs_to_merc.transform(lon, lat)
    A = np.c_[np.ones(len(mx)), mx, my]
    cu = np.linalg.lstsq(A, res[:, 0], rcond=None)[0]
    cv = np.linalg.lstsq(A, res[:, 1], rcond=None)[0]
    pts = item["target"]["selector"]["value"].split('points="')[1].split('"')[0]
    poly = [tuple(float(v) * s for v in p.split(",")) for p in pts.split()]
    im = Image.open(img_path).convert("RGB")
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).polygon(poly, fill=255)
    B = np.linalg.inv(np.array([[cu[1], cu[2]], [cv[1], cv[2]]]))
    pred = (B @ (res - [cu[0], cv[0]]).T).T
    resid_m = np.hypot(pred[:, 0] - mx, pred[:, 1] - my) * np.cos(np.radians(lat))
    return {"im": im, "mask": np.asarray(mask) > 0, "poly": poly, "cu": cu, "cv": cv, "B": B,
            "resid_m": [round(float(r), 1) for r in resid_m]}


def warp_1940(g):
    rgba = np.dstack([np.asarray(g["im"]), g["mask"] * 255]).astype(float)
    cu, cv, B = g["cu"], g["cv"], g["B"]
    corners_m = (B @ (np.array(g["poly"]) - [cu[0], cv[0]]).T).T
    xmin, ymin = corners_m.min(0)
    xmax, ymax = corners_m.max(0)
    nx, ny = int((xmax - xmin) / CELL), int((ymax - ymin) / CELL)
    GX, GY = np.meshgrid(xmin + (np.arange(nx) + 0.5) * CELL, ymax - (np.arange(ny) + 0.5) * CELL)
    U = cu[0] + cu[1] * GX + cu[2] * GY
    V = cv[0] + cv[1] * GX + cv[2] * GY
    out = np.zeros((ny, nx, 4))
    for k in range(4):
        out[..., k] = ndi.map_coordinates(rgba[..., k], [V, U], order=1, mode="constant", cval=0)
    WEB.mkdir(exist_ok=True)
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA").save(WEB / "map1940.webp", quality=72, method=6)
    (lon0, lon1), (lat0, lat1) = merc_to_wgs.transform([xmin, xmax], [ymin, ymax])
    meta = {"bounds": [[lat0, lon0], [lat1, lon1]], "size_px": [nx, ny], "gcp_residual_m": g["resid_m"]}
    print("1940 map:", meta)
    return meta


def classes_1940(g):
    """Per-pixel reading of the 1940 map: 1 destroyed (orange), 2 repairable or undamaged (a white hole
    inside the orange area), 0 outside, -1 off the sheet."""
    lab = rgb2lab(np.asarray(g["im"]) / 255.0)
    L, A, Bb = lab[..., 0], lab[..., 1], lab[..., 2]
    orange = ndi.binary_opening((Bb > 19) & (A > 3) & (L > 55), iterations=1)
    closed = ndi.binary_closing(orange, iterations=2)
    holes = ndi.binary_fill_holes(closed) & ~orange
    holes = ndi.binary_opening(holes, iterations=1)                 # drop thin street lines
    lab_, n = ndi.label(holes)
    sizes = ndi.sum(holes, lab_, range(1, n + 1))
    holes = np.isin(lab_, 1 + np.nonzero(sizes >= 10)[0])          # >= ~30 m2
    cls = np.zeros(orange.shape, np.int8)
    cls[holes] = 2
    cls[orange] = 1
    cls[~g["mask"]] = -1
    return cls


def read_1940(cls, g, xs, ys):
    """Majority class in a 3 x 3 pixel window (about 5 m) around RD points."""
    mx, my = rd_to_merc.transform(np.asarray(xs), np.asarray(ys))
    u = np.rint(g["cu"][0] + g["cu"][1] * mx + g["cu"][2] * my).astype(int)
    v = np.rint(g["cv"][0] + g["cv"][1] * mx + g["cv"][2] * my).astype(int)
    h, w = cls.shape
    out = np.full(len(u), -1, np.int8)
    for i, (uu, vv) in enumerate(zip(u, v)):
        if 1 <= uu < w - 1 and 1 <= vv < h - 1:
            win = cls[vv - 1:vv + 2, uu - 1:uu + 2].ravel()
            if (win == -1).any():
                continue
            c = Counter(win.tolist())
            out[i] = 1 if c[1] >= 5 else (2 if c[2] >= 3 else (1 if c[1] >= 3 else 0))
    return out


# --- today's buildings --------------------------------------------------------------------------------

def addresses():
    """Short address label per BAG pand: '<street> <n>' or '<street> <n>–<m>', '+' when more streets."""
    f = RAW / "bag_vbo.gpkg"
    if not f.exists():
        return {}
    v = gpd.read_file(f, ignore_geometry=True)
    by_pand = defaultdict(lambda: defaultdict(list))
    for street, num, let, pids in zip(v["openbare_ruimte"], v["huisnummer"], v["huisletter"], v["pandidentificatie"]):
        if not isinstance(pids, str) or not isinstance(street, str):
            continue
        for pid in re.split(r"[,\s]+", pids.strip()):
            if pid:
                by_pand[pid][street].append((int(num), let or ""))
    out = {}
    for pid, streets in by_pand.items():
        street, nums = max(streets.items(), key=lambda kv: len(kv[1]))
        nums = sorted(set(nums))
        lo, hi = nums[0], nums[-1]
        label = f"{street} {lo[0]}{lo[1]}" if lo == hi else f"{street} {lo[0]}{lo[1]}–{hi[0]}{hi[1]}"
        out[pid] = label + (" +" if len(streets) > 1 else "")
    return out


def uses(s):
    if not isinstance(s, str):
        return ""
    return ", ".join(dict.fromkeys(USES.get(x.strip(), x.strip()) for x in s.split(",") if x.strip()))


def lost_buildings(b, cls, g):
    """Wikidata items with a demolition date in 1940, buildings only, with what stands on the spot now."""
    f = RAW / "wikidata_ended_1940.json"
    if not f.exists():
        return [], 0
    rows = json.loads(f.read_text())["results"]["bindings"]
    items = {}
    for r in rows:
        q = r["item"]["value"].rsplit("/", 1)[-1]
        it = items.setdefault(q, {"types": set()})
        val = lambda k: r.get(k, {}).get("value")
        if val("inst_nl"):
            it["types"].add(val("inst_nl"))
        for k in ("label_en", "label_nl", "coord", "inception", "end", "nlwiki", "enwiki"):
            if val(k) and k not in it:
                it[k] = val(k)
    lost, skipped = [], 0
    sindex = b.sindex
    for q, it in items.items():
        kinds = [LOST_TYPES[t] for t in it["types"] if t in LOST_TYPES]
        if not kinds or "coord" not in it or q in NOT_LOST:
            skipped += 1
            continue
        lon, lat = map(float, re.findall(r"[-\d.]+", it["coord"])[:2])
        x, y = Transformer.from_crs(4326, 28992, always_xy=True).transform(lon, lat)
        p = Point(x, y)
        cand = b.iloc[list(sindex.query(p.buffer(25)))]
        now = None
        if len(cand):
            d = cand.distance(p)
            k = d.idxmin()
            if d[k] <= 25:
                now = {"y": int(cand.at[k, "bouwjaar"]), "a": cand.at[k, "a"], "u": cand.at[k, "u"],
                       "on": bool(d[k] == 0)}
        end = it.get("end", "")
        lost.append({"q": q, "name": it.get("label_en") or it.get("label_nl") or q,
                     "name_nl": it.get("label_nl"), "kind": kinds[0],
                     "built": (it.get("inception") or "")[:4] or None,
                     "end": end[:10], "may14": end[:10] == "1940-05-14",
                     "wiki": it.get("enwiki") or it.get("nlwiki"), "lon": round(lon, 6), "lat": round(lat, 6),
                     "c40": int(read_1940(cls, g, [x], [y])[0]), "now": now})
    return sorted(lost, key=lambda r: r["name"]), skipped


def to_geojson_wgs(gdf, props, ndigits=6):
    g = gdf.to_crs(4326)
    feats = []
    for geom, *vals in zip(g.geometry, *[g[p] for p in props]):
        gj = mapping(geom)

        def rnd(c):
            if isinstance(c[0], (float, int)):
                return [round(c[0], ndigits), round(c[1], ndigits)]
            return [rnd(x) for x in c]
        props_out = {}
        for p, v in zip(props, vals):
            if isinstance(v, (np.integer, int)):
                v = int(v)
            if v == "" or v is None:
                continue
            props_out[p] = v
        feats.append({"type": "Feature", "properties": props_out,
                      "geometry": {"type": gj["type"], "coordinates": rnd(gj["coordinates"])}})
    return {"type": "FeatureCollection", "features": feats}


def layers(g, cls):
    b = gpd.read_file(RAW / "bag_pand.gpkg", bbox=(X0, Y0, X1, Y1))
    b = b[b["status"].isin(STANDING) & b["bouwjaar"].between(1000, 2030)].copy()
    b["y"] = b["bouwjaar"].astype(int)
    adr = addresses()
    b["a"] = b["identificatie"].map(adr).fillna("")
    b["u"] = b["gebruiksdoel"].map(uses)
    rp = b.geometry.representative_point()
    b["c"] = read_1940(cls, g, rp.x.values, rp.y.values)
    zone = gpd.read_file(DATA / "brandgrens_zone.geojson")
    Z = unary_union(zone.geometry.values)
    b["z"] = rp.within(Z).astype(int)
    b["i"] = b["identificatie"].str[4:]                  # drop the '0599' municipality prefix to save space
    lost, skipped = lost_buildings(b, cls, g)
    b["geometry"] = b.geometry.simplify(0.3, preserve_topology=True)
    w = gpd.read_file(RAW / "bgt_waterdeel.gpkg", bbox=(X0, Y0, X1, Y1))
    w = w[w["eind_registratie"].isna()]
    water = unary_union(w.geometry.values).intersection(box(X0, Y0, X1, Y1)).simplify(1.0)
    water = gpd.GeoDataFrame({"k": [1]}, geometry=[water], crs=28992)
    line = gpd.read_file(DATA / "brandgrens_line.geojson")
    lights = gpd.read_file(DATA / "brandgrens_lights.geojson")
    lights["c"] = lights["colour"]
    stats = json.loads((DATA / "stats.json").read_text())
    inside = b[b["z"] == 1]
    stats["map1940"] = {"inside_line_on_destroyed": int((inside["c"] == 1).sum()),
                        "inside_line_on_survivor": int((inside["c"] == 2).sum()),
                        "survivor_spots_still_pre1940": int(((inside["c"] == 2) & (inside["y"] < 1940)).sum()),
                        "survivor_spots_now_post1940": int(((inside["c"] == 2) & (inside["y"] >= 1940)).sum()),
                        "lost_buildings_wikidata": len(lost), "wikidata_items_skipped": skipped}
    print("1940 reading:", stats["map1940"], "| addresses for", int((b["a"] != "").sum()), "of", len(b))
    # keep the 1940-map reading in data/stats.json too, next to the other findings
    disk = json.loads((DATA / "stats.json").read_text())
    disk["map1940"] = stats["map1940"]
    (DATA / "stats.json").write_text(json.dumps(disk, indent=1, ensure_ascii=False))
    return {"buildings": to_geojson_wgs(b[["y", "a", "u", "c", "z", "i", "geometry"]], ["y", "a", "u", "c", "z", "i"]),
            "water": to_geojson_wgs(water, []),
            "line": to_geojson_wgs(line[["colour", "geometry"]], ["colour"]),
            "lights": to_geojson_wgs(lights[["c", "geometry"]], ["c"]),
            "lost": lost, "stats": stats, "n_buildings": int(len(b))}


# --- output -------------------------------------------------------------------------------------------

def standalone():
    """index.html with data, the 1940 image and Leaflet inline: one file to send around."""
    VENDOR.mkdir(parents=True, exist_ok=True)
    for name in ("leaflet.js", "leaflet.css"):
        f = VENDOR / name
        if not f.exists():
            r = requests.get(LEAFLET + name, timeout=60)
            r.raise_for_status()
            f.write_bytes(r.content)
    html = (HERE / "index.html").read_text()
    css = (VENDOR / "leaflet.css").read_text()
    js = (VENDOR / "leaflet.js").read_text()
    img = "data:image/webp;base64," + base64.b64encode((WEB / "map1940.webp").read_bytes()).decode()
    html = re.sub(r'<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"[^>]*>',
                  lambda m: f"<style>\n{css}\n</style>", html)
    html = re.sub(r'<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"[^>]*></script>',
                  lambda m: f"<script>\n{js}\n</script>", html)
    for name in ("context", "buildings"):
        data = (WEB / f"{name}.js").read_text()
        html = html.replace(f'<script src="web/{name}.js"></script>', f"<script>\n{data}</script>")
    html = html.replace('"web/map1940.webp"', json.dumps(img))
    assert "web/" not in html.split("</style>")[-1].replace("github.com/m-erts", ""), "a relative web/ path is left"
    out = HERE / "rotterdam-1940.html"
    out.write_text(html)
    print(f"{out.name}: {out.stat().st_size / 1e6:.1f} MB (single file)")


def main():
    g = georef_1940()
    meta = warp_1940(g)
    cls = classes_1940(g)
    d = layers(g, cls)
    d["map1940"] = meta
    for name, keys in {"buildings": ["buildings"],
                       "context": ["water", "line", "lights", "lost", "stats", "map1940"]}.items():
        payload = {k: d[k] for k in keys}
        f = WEB / f"{name}.js"
        f.write_text(f"window.D6 = Object.assign(window.D6 || {{}}, {json.dumps(payload, separators=(',', ':'), ensure_ascii=False)});\n")
        print(f"{f.name}: {f.stat().st_size / 1e6:.1f} MB")
    print("buildings:", d["n_buildings"], "| lost (Wikidata):", len(d["lost"]),
          "| webp:", f"{(WEB / 'map1940.webp').stat().st_size / 1e6:.1f} MB")
    standalone()


if __name__ == "__main__":
    main()
