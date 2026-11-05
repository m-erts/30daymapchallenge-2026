"""Day 5 interactive: index.html, one self-contained file (MapLibre GL 4.7.1, own base maps and all layers inlined,
no tiles, opens from disk). London and Paris side by side at the same ground scale.

Layers per city: a quiet base (water, parks, roads; rendered from Overture/OSM and warped to Web Mercator), the
overview 50 m share grid (zoom < 14), the 5 m classes (zoom >= 14; whole dome, upper dome, lantern only, and open
ground that sees nothing), the protected zones (LVMF corridors / the dome's faisceau de vues). A click anywhere reads
the 5 m result under the cursor from the same class layers (which part of the dome is seen, or a building/tree cell),
the distance to the dome and whether the point lies in the protected zone. The London markers A, B, C open the three sections of the second frame.

    python make_web.py           # index.html (~9 MB)
"""
import base64
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "paris"))
import matplotlib as mpl           # noqa: E402
mpl.use("Agg")
import detail as DT                # noqa: E402
import geopandas as gpd            # noqa: E402
import matplotlib.pyplot as plt    # noqa: E402
import numpy as np                 # noqa: E402
import paris_apur as PA            # noqa: E402
import public_space as PS          # noqa: E402
import rasterio                    # noqa: E402
import story as ST                 # noqa: E402
from PIL import Image              # noqa: E402
from pyproj import Transformer     # noqa: E402
from rasterio.features import rasterize  # noqa: E402
from rasterio.warp import Resampling, calculate_default_transform, reproject  # noqa: E402

S, P0, L0, CLEAN, VIS, P = PA.S, PA.P0, PA.L0, PA.CLEAN, PA.VIS, PA.P
VENDOR = HERE / "data" / "raw" / "vendor"


def warp(arr, src_T, src_crs, resampling, res=None, nodata=0):
    """Warp a (bands, h, w) array to EPSG:3857; returns the array and its lon/lat corner coordinates."""
    bands, h, w = arr.shape
    left, top = src_T.c, src_T.f
    right, bottom = left + w * src_T.a, top + h * src_T.e
    dst_T, dw, dh = calculate_default_transform(src_crs, 3857, w, h, left, bottom, right, top, resolution=res)
    out = np.full((bands, dh, dw), nodata, dtype=arr.dtype)
    for b in range(bands):
        reproject(arr[b], out[b], src_transform=src_T, src_crs=src_crs, dst_transform=dst_T, dst_crs=3857,
                  resampling=resampling, src_nodata=nodata, dst_nodata=nodata)
    tr = Transformer.from_crs(3857, 4326, always_xy=True)
    x0, y0 = dst_T.c, dst_T.f
    x1, y1 = x0 + dw * dst_T.a, y0 + dh * dst_T.e
    corners = [tr.transform(x0, y0), tr.transform(x1, y0), tr.transform(x1, y1), tr.transform(x0, y1)]
    return out, [[round(a, 6), round(b, 6)] for a, b in corners]


def png_uri(img, mode=None, colours=None):
    im = Image.fromarray(img, mode) if mode else Image.fromarray(img)
    if colours:
        im = im.convert("RGBA").quantize(colors=colours, method=Image.Quantize.FASTOCTREE)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def mask_png(mask, colour):
    """A boolean layer as a 1-bit palette PNG (index 0 transparent): a fraction of the RGBA size."""
    im = Image.fromarray(mask.astype(np.uint8), "P")
    r, g, b = [int(255 * v) for v in mpl.colors.to_rgb(colour)]
    im.putpalette([0, 0, 0, r, g, b])
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True, transparency=0, bits=1)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def alpha_png(alpha, colour, levels=16):
    """Coverage (0..1) as a 4-bit palette PNG of one colour with 16 alpha steps (tRNS): smooth, small, honest."""
    q = np.clip(np.round(alpha * (levels - 1)), 0, levels - 1).astype(np.uint8)
    im = Image.fromarray(q, "P")
    r, g, b = [int(255 * v) for v in mpl.colors.to_rgb(colour)]
    im.putpalette([r, g, b] * levels)
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True, transparency=bytes(int(round(i * 255 / (levels - 1))) for i in range(levels)),
            bits={2: 1, 4: 2, 16: 4}[levels])
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def coverage(mask, block):
    """Share of each block's area covered by the mask, boosted by a square root so that thin streets stay visible
    when zoomed out (monotonic, never more than 1, never anything where the mask is empty)."""
    h, w = (mask.shape[0] // block) * block, (mask.shape[1] // block) * block
    cov = mask[:h, :w].reshape(h // block, block, w // block, block).mean(axis=(1, 3))
    return np.sqrt(cov), (h, w)


def rgba_layer(mask, colour):
    rgba = np.zeros(mask.shape + (4,), dtype=np.uint8)
    rgba[mask] = (*[int(255 * v) for v in mpl.colors.to_rgb(colour)], 255)
    return rgba


def geojson(gdf, props=()):
    g = gdf.to_crs(4326)
    feats = []
    for _, r in g.iterrows():
        geom = r.geometry.simplify(0.00002)
        feats.append({"type": "Feature", "geometry": json.loads(gpd.GeoSeries([geom]).to_json())["features"][0]["geometry"],
                      "properties": {k: r[k] for k in props}})
    return {"type": "FeatureCollection", "features": feats}


def section_png(Ld, k, lang):
    t = DT.TXT[lang]
    sec = DT.section(Ld, DT.SECTIONS[k])
    fig = plt.figure(figsize=(4.2, 1.9), dpi=150)
    ax = fig.add_axes([0.12, 0.2, 0.85, 0.62])
    DT.draw_section(ax, sec, t, lang)
    lc = DT.lowest_class(sec["res"])
    fig.text(0.02, 0.97, t["sec"][k], fontproperties=S.font("label_bold", lang, 7.5), color=P["accent3"], va="top")
    fig.text(0.02, 0.9, t["dist"].format(d=sec["D"] / 1000).replace(".", "," if lang == "ru" else ".") + " · " + t["verdict"][lc],
             fontproperties=S.font("label", lang, 6.5), color=VIS[3] if lc else DT.BLOCK, va="top")
    ax.set_xlabel(t["xlab"], fontproperties=S.font("label", lang, 5.5), color=P["muted"], labelpad=1)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def build():
    S.apply()
    Ld = DT.london()
    DP = PA.paris_layers()
    data = {}
    for key in ("london", "paris"):
        C = ST.city(key, Ld, DP)
        if key == "london":
            lev, open_, T, wm, crs = Ld["lev"], Ld["open"], Ld["T"], Ld["wm"], 27700
            pub = np.unpackbits(np.load(L0.DER / "public_mask.npy"))[:lev.size].reshape(lev.shape).astype(bool)
            g = Ld["g"]
            zone_polys = g[(g.TYPE == "VC") & g.stpauls]
            other_polys = g[(g.TYPE == "VC") & ~g.stpauls]
            pts = L0.places(g).drop_duplicates(subset="place")
            pts = pts.assign(name=pts.place, own=pts.stpauls.astype(int))[["name", "own", "geometry"]]
            axis = Ld["axis"]; levels = [float(v) for v in Ld["levels"]]
        else:
            lev, open_, T, wm, crs = DP["levs"]["sacrecoeur"], DP["open"], DP["T"], DP["water_mask"], 2154
            pub = np.unpackbits(np.load(P0.DER / "public_mask.npy"))[:lev.size].reshape(lev.shape).astype(bool)
            g = DP["g"]
            zone_polys = g[g.fuseau == P0.DOMES["sacrecoeur"]["letter"]].dissolve()
            other_polys = g[g.fuseau != P0.DOMES["sacrecoeur"]["letter"]].dissolve(by="fuseau").reset_index()
            pp = P0.panorama_points(g)
            pts = gpd.GeoDataFrame(dict(name=pp["name"], own=0), geometry=pp.geometry, crs=2154)
            axis = DP["stats"]["domes"]["sacrecoeur"]["axis_l93"]
            levels = [float(v) for v in DP["stats"]["domes"]["sacrecoeur"]["levels_m_above_ground"]]
        zone = rasterize([(geom, 1) for geom in zone_polys.geometry], out_shape=lev.shape, transform=T, fill=0).astype(bool)
        # base: the story's quiet base raster (6 m), warped
        base = np.moveaxis(C["base"], 2, 0)
        bT = rasterio.transform.from_origin(C["full"][0], C["full"][3], ST.BASE_RES, ST.BASE_RES)
        base_w, base_c = warp(base, bT, crs, Resampling.bilinear, nodata=0)
        base_w[:, (base_w == 0).all(axis=0)] = 255
        # 5 m layers
        cls = np.where((lev != 255) & open_, L0.CLASS_OF_LEVEL[np.minimum(lev, 6)], 0)
        layers5, pyramid = {}, {}
        for name, mask, col in (("whole", cls == 3, VIS[3]), ("upper", cls == 2, VIS[2]), ("lantern", cls == 1, VIS[1]),
                                ("blind", open_ & (cls == 0) & ~wm, DT.NOVIEW)):
            lw_, lc_ = warp(mask.astype(np.uint8)[None], T, crs, Resampling.nearest, nodata=0)
            layers5[name] = (mask_png(lw_[0] > 0, col), lc_)
            pyramid[name] = {}
            for block in (2, 4, 8):                                  # 10, 20 and 40 m
                cov, (hh, ww) = coverage(mask, block)
                bT = rasterio.transform.from_origin(T.c, T.f, T.a * block, -T.e * block)
                cw_, cc_ = warp((cov * 255).astype(np.uint8)[None], bT, crs, Resampling.nearest, nodata=0)
                pyramid[name][str(5 * block)] = (alpha_png(cw_[0] / 255, col, levels=4 if name == "blind" else 16), cc_)
        tr = Transformer.from_crs(crs, 4326, always_xy=True)
        lon, lat = tr.transform(*axis)
        st = json.loads(((L0.DER if key == "london" else P0.DER) / "stats.json").read_text())
        data[key] = dict(
            base=(png_uri(np.moveaxis(base_w, 0, 2), "RGB", colours=96), base_c),
            layers5={k: list(v) for k, v in layers5.items()}, pyramid={k: {m: list(v) for m, v in lv.items()} for k, lv in pyramid.items()},
            zone=geojson(zone_polys), other=geojson(other_polys), points=geojson(pts, ("name", "own")),
            dome=[round(lon, 6), round(lat, 6)], levels=levels)
        print(key, "layers ready", flush=True)
    # sections for the London markers
    tr = Transformer.from_crs(27700, 4326, always_xy=True)
    data["sections"] = {k: dict(lonlat=[round(v, 6) for v in tr.transform(*xy)], png={lang: section_png(Ld, k, lang) for lang in ("en", "ru")})
                        for k, xy in DT.SECTIONS.items()}
    ls = json.loads((L0.DER / "stats.json").read_text())
    ps = json.loads((P0.DER / "stats.json").read_text())
    data["numbers"] = dict(
        london=dict(sees=ls["sees_any_km2"], share=100 * ls["sees_any_km2"] / ls["open_ground_km2"],
                    pub=100 * ls["public_space"]["public_sees_any_share"], inside=100 * (1 - ls["sees_any_outside_vc_share"]),
                    blind=100 * (1 - ls["vc_stpauls_open_sees_any_km2"] / ls["vc_stpauls_open_km2"]), water=100 * ls["public_space"]["open_seeing_on_water_share"]),
        paris=dict(sees=ps["domes"]["sacrecoeur"]["sees_any_km2"], share=100 * ps["domes"]["sacrecoeur"]["sees_any_share_of_open"],
                   pub=100 * ps["public_space"]["sacrecoeur"]["public_sees_any_share"],
                   inside=100 * (1 - ps["domes"]["sacrecoeur"]["sees_any_outside_own_fuseau_share"]),
                   blind=100 * ps["domes"]["sacrecoeur"]["own_fuseau"]["blind_share"],
                   outside_paris=100 * (1 - ps["domes"]["sacrecoeur"]["within_paris"]["sees_any_km2"] / ps["domes"]["sacrecoeur"]["sees_any_km2"])))
    return data


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Day 5 · Where is the dome actually visible from?</title>
<style>__CSS__</style>
<style>
:root{--ink:#231F20;--muted:#6D6E71;--navy:#16223D;--bg:#FFFFFF;--line:#E3E1DC;--corr:#F28522;--fus:#9E4F51;
 --whole:__WHOLE__;--upper:__UPPER__;--lantern:__LANTERN__;--blind:#E2DED6;--water:#D3E4EC;--park:#E2EBDA}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);
 font-family:"Source Sans 3","Source Sans Pro","Segoe UI",Helvetica,Arial,sans-serif}
header{padding:14px 18px 6px}h1{margin:0;font-size:20px;color:var(--navy);font-weight:600}
.sub{margin:4px 0 0;font-size:13px;color:var(--muted);max-width:1100px;line-height:1.35}
.bar{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center;padding:6px 18px 8px;font-size:13px;border-bottom:1px solid var(--line)}
.bar label{display:inline-flex;align-items:center;gap:5px;cursor:pointer;white-space:nowrap}
.sw{display:inline-block;width:14px;height:10px;border-radius:1px}.ln{display:inline-block;width:16px;height:0;border-top:2px solid}
.lang{margin-left:auto}.lang button{border:1px solid var(--line);background:#fff;padding:2px 8px;cursor:pointer;font:inherit}
.lang button.on{background:var(--navy);color:#fff;border-color:var(--navy)}
main{display:flex;gap:8px;padding:8px 18px;height:calc(100% - 230px);min-height:420px}
.col{flex:1;display:flex;flex-direction:column;min-width:0}.col h2{margin:0 0 4px;font-size:15px;color:var(--navy);font-weight:600}
.map{flex:1;border:1px solid var(--line);border-radius:2px;min-height:300px}
.nums{font-size:13px;color:var(--muted);margin-top:5px;line-height:1.4}.nums b{color:var(--whole);font-size:15px}
footer{padding:4px 18px 10px;font-size:11px;color:var(--muted);line-height:1.4}
.maplibregl-popup-content{font-size:13px;line-height:1.35;max-width:640px}.pop b{color:var(--navy)}
@media (max-width:800px){main{flex-direction:column;height:auto}.map{height:60vh}}
</style></head><body>
<header><h1 id="t"></h1><p class="sub" id="s"></p></header>
<div class="bar">
 <label><input type="checkbox" id="c_zone" checked><span class="ln" style="border-top:2px dashed #6D6E71"></span><span id="l_zone"></span></label>
 <label><input type="checkbox" id="c_other"><span class="ln" style="border-color:#A9A6A0"></span><span id="l_other"></span></label>
 <label><input type="checkbox" id="c_whole" checked><span class="sw" style="background:var(--whole)"></span><span id="l_whole"></span></label>
 <label><input type="checkbox" id="c_upper" checked><span class="sw" style="background:var(--upper)"></span><span id="l_upper"></span></label>
 <label><input type="checkbox" id="c_lantern" checked><span class="sw" style="background:var(--lantern)"></span><span id="l_lantern"></span></label>
 <label><input type="checkbox" id="c_blind"><span class="sw" style="background:var(--blind)"></span><span id="l_blind"></span></label>
 <label><input type="checkbox" id="c_base" checked><span class="sw" style="background:var(--park)"></span><span id="l_base"></span></label>
 <span id="l_hint" style="color:var(--muted)"></span>
 <span class="lang"><button id="b_en">EN</button><button id="b_ru">RU</button></span>
</div>
<main>
 <div class="col"><h2 id="h_london"></h2><div class="map" id="m_london"></div><div class="nums" id="n_london"></div></div>
 <div class="col"><h2 id="h_paris"></h2><div class="map" id="m_paris"></div><div class="nums" id="n_paris"></div></div>
</main>
<footer id="f"></footer>
<script>__JS__</script>
<script>
const D = __DATA__;
const T = {
 en:{t:"Where is the dome actually visible from? London and Paris, side by side at the same ground scale",
  s:"Each city protects views of its dome by law: London with eight LVMF corridors from its hills to St Paul's, Paris with a faisceau de vues for the Sacré-Cœur in its PLU. The blue cells show where the dome is actually visible from street level, by line of sight across the LiDAR surface of buildings and trees (eye 1.6 m, 5 m cells). Zoomed out, the 5 m cells are merged and drawn fainter where they cover less of the ground; zoom in for the individual cells. The switches act at every scale. Click anywhere to read the result; click A, B, C in London for a cut along the line of sight.",
  zone:"protected zone for the dome", other:"other protected views", whole:"whole dome", upper:"upper dome", lantern:"lantern only", blind:"open ground, dome not visible", base:"base map",
  hint:"", h_london:"London · St Paul's Cathedral", h_paris:"Paris · Sacré-Cœur de Montmartre",
  n_london:(n)=>`Sees the dome: <b>${n.share.toFixed(1)}%</b> of the open ground (${n.sees.toFixed(1)} km²), <b>${n.pub.toFixed(1)}%</b> of streets, squares and parks. Inside the 8 corridors: <b>${n.inside.toFixed(0)}%</b> of the seeing ground; ${n.blind.toFixed(0)}% of the corridors' open ground sees nothing. ${n.water.toFixed(0)}% of the seeing ground is the Thames.`,
  n_paris:(n)=>`Sees the dome: <b>${n.share.toFixed(1)}%</b> of the open ground (${n.sees.toFixed(1)} km²), <b>${n.pub.toFixed(1)}%</b> of streets, squares and parks. Inside its faisceau de vues: <b>${n.inside.toFixed(0)}%</b> of the seeing ground; ${n.blind.toFixed(0)}% of the faisceau's open ground sees nothing. ${n.outside_paris.toFixed(0)}% of the seeing ground lies outside Paris.`,
  f:"Data: GLA, LVMF protected vistas (OGL v2) · Environment Agency LiDAR composite DSM/DTM (OGL v3) · Ville de Paris, PLU bioclimatique, fuseaux de protection (ODbL) · IGN LiDAR HD (Licence Ouverte 2.0) · OpenStreetMap and Overture Maps (ODbL). Map library: MapLibre GL JS (BSD-3). Code and method: github.com/m-erts/30daymapchallenge-2026, days/05-sight. Analysis: Marija Ercegovac · #30DayMapChallenge day 5",
  cls:{1:"only the lantern and cross", 2:"the upper dome", 3:"the whole dome, down to its base"},
  seen:"From this 5 m cell you see", none:"From here the dome is not visible.", notopen:"Building or tree canopy here: not a street-level viewer cell.",
  dist:"km to the dome", inzone:"inside the protected zone", outzone:"outside the protected zone"},
 ru:{t:"Откуда купол виден на самом деле? Лондон и Париж рядом, в одном масштабе",
  s:"Оба города охраняют вид на свой купол законом: Лондон восемью коридорами LVMF с холмов на собор св. Павла, Париж пучком видов на Сакре-Кёр в своём PLU. Синие ячейки показывают, откуда купол действительно виден с уровня улицы по лучу зрения через LiDAR-поверхность зданий и деревьев (глаз 1,6 м, ячейки 5 м). На мелком масштабе ячейки 5 м объединены и тем бледнее, чем меньше земли они покрывают; приблизьте, чтобы увидеть отдельные ячейки. Галочки работают на любом масштабе. Клик в любом месте показывает результат; A, B, C в Лондоне открывают разрез вдоль луча зрения.",
  zone:"охраняемая зона для купола", other:"другие охраняемые виды", whole:"весь купол", upper:"верх купола", lantern:"только фонарь", blind:"открытая земля, купол не виден", base:"основа",
  hint:"", h_london:"Лондон · собор св. Павла", h_paris:"Париж · Сакре-Кёр на Монмартре",
  n_london:(n)=>`Купол видят <b>${n.share.toFixed(1).replace('.',',')}%</b> открытой земли (${n.sees.toFixed(1).replace('.',',')} км²) и <b>${n.pub.toFixed(1).replace('.',',')}%</b> улиц, площадей и парков. Внутри 8 коридоров: <b>${n.inside.toFixed(0)}%</b> видящей земли; ${n.blind.toFixed(0)}% открытой земли коридоров купол не видят. ${n.water.toFixed(0)}% видящей земли это Темза.`,
  n_paris:(n)=>`Купол видят <b>${n.share.toFixed(1).replace('.',',')}%</b> открытой земли (${n.sees.toFixed(1).replace('.',',')} км²) и <b>${n.pub.toFixed(1).replace('.',',')}%</b> улиц, площадей и парков. Внутри пучка видов: <b>${n.inside.toFixed(0)}%</b> видящей земли; ${n.blind.toFixed(0)}% открытой земли пучка купол не видят. ${n.outside_paris.toFixed(0)}% видящей земли лежит за границей Парижа.`,
  f:"Данные: GLA, LVMF protected vistas (OGL v2) · Environment Agency, LiDAR DSM/DTM (OGL v3) · Ville de Paris, PLU bioclimatique, fuseaux de protection (ODbL) · IGN LiDAR HD (Licence Ouverte 2.0) · OpenStreetMap и Overture Maps (ODbL). Библиотека карт: MapLibre GL JS (BSD-3). Код и метод: github.com/m-erts/30daymapchallenge-2026, days/05-sight. Расчёт: Мария Эрцеговац · #30DayMapChallenge день 5",
  cls:{1:"только фонарь и крест", 2:"верх купола", 3:"весь купол, до основания"},
  seen:"Из этой ячейки 5 м видно", none:"Отсюда купол не виден.", notopen:"Здесь здание или крона: это не точка наблюдения на уровне улицы.",
  dist:"км до купола", inzone:"внутри охраняемой зоны", outzone:"вне охраняемой зоны"}
};
let lang = (navigator.language || "en").startsWith("ru") ? "ru" : "en";
// same ground scale in both maps: Web Mercator metres per pixel scale with cos(latitude)
const dz = Math.log2(Math.cos(D.paris.dome[1] * Math.PI / 180) / Math.cos(D.london.dome[1] * Math.PI / 180));
const maps = {}, query = {};
function loadQuery(key){
  query[key] = {};
  for (const n of ["whole", "upper", "lantern", "blind"]) {
    const [uri, corners] = D[key].layers5[n];
    const img = new Image();
    img.onload = () => { const c = document.createElement("canvas"); c.width = img.naturalWidth; c.height = img.naturalHeight;
      const ctx = c.getContext("2d", {willReadFrequently:true}); ctx.drawImage(img, 0, 0);
      query[key][n] = {data: ctx.getImageData(0, 0, c.width, c.height).data, corners, size:[c.width, c.height]}; };
    img.src = uri;
  }
}
function merc(lon, lat){ const x = lon * Math.PI / 180, y = Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)); return [x, y]; }
function hit(q, lngLat){
  const [tl, tr, br, bl] = q.corners; const a = merc(tl[0], tl[1]), b = merc(br[0], br[1]), p = merc(lngLat.lng, lngLat.lat);
  const i = Math.floor((p[0] - a[0]) / (b[0] - a[0]) * q.size[0]), j = Math.floor((a[1] - p[1]) / (a[1] - b[1]) * q.size[1]);
  if (i < 0 || j < 0 || i >= q.size[0] || j >= q.size[1]) return null;
  return q.data[(j * q.size[0] + i) * 4 + 3] > 0;
}
function sample(key, lngLat){       // 3 whole dome, 2 upper dome, 1 lantern only, 0 open ground that sees nothing, -1 building or tree
  const q = query[key]; if (!q || Object.keys(q).length < 4) return null;
  const inside = hit(q.whole, lngLat); if (inside === null) return null;
  if (inside) return 3; if (hit(q.upper, lngLat)) return 2; if (hit(q.lantern, lngLat)) return 1; if (hit(q.blind, lngLat)) return 0;
  return -1;
}
function inRing(pt, ring){ let c = false; for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
  const [xi, yi] = ring[i], [xj, yj] = ring[j];
  if (((yi > pt[1]) !== (yj > pt[1])) && (pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi)) c = !c; } return c; }
function inZone(key, pt){ for (const f of D[key].zone.features) { const g = f.geometry;
  const polys = g.type === "Polygon" ? [g.coordinates] : g.coordinates;
  for (const p of polys) if (inRing(pt, p[0]) && !p.slice(1).some(h => inRing(pt, h))) return true; } return false; }
function hav(a, b){ const R = 6371, r = Math.PI / 180, dl = (b[1] - a[1]) * r, dn = (b[0] - a[0]) * r;
  const h = Math.sin(dl / 2) ** 2 + Math.cos(a[1] * r) * Math.cos(b[1] * r) * Math.sin(dn / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(h)); }
function popup(key, e){
  const L = T[lang], c = sample(key, e.lngLat); if (c === null) return;
  const pt = [e.lngLat.lng, e.lngLat.lat], d = hav(pt, D[key].dome), fmt = (v, n) => lang === "ru" ? v.toFixed(n).replace(".", ",") : v.toFixed(n);
  let html = `<div class="pop">`;
  if (c < 0) html += L.notopen; else if (c === 0) html += `<b>${L.none}</b>`; else html += `${L.seen} <b>${L.cls[c]}</b>.`;
  html += `<br>${fmt(d, 2)} ${L.dist} · ${inZone(key, pt) ? L.inzone : L.outzone}</div>`;
  new maplibregl.Popup({maxWidth:"360px"}).setLngLat(e.lngLat).setHTML(html).addTo(maps[key]);
}
function build(key){
  const d = D[key];
  const style = {version:8, sources:{}, layers:[{id:"bg", type:"background", paint:{"background-color":"#F7F6F3"}}]};
  const img = (id, src, corners, extra) => { style.sources[id] = {type:"image", url:src, coordinates:corners};
    style.layers.push(Object.assign({id, type:"raster", source:id, paint:{"raster-resampling":"nearest","raster-fade-duration":0}}, extra || {})); };
  img("base", d.base[0], d.base[1], {paint:{"raster-resampling":"linear","raster-fade-duration":0}});
  const LEVELS = [["40", 0, 11.5], ["20", 11.5, 12.5], ["10", 12.5, 13.5], ["5", 13.5, 24]];
  for (const n of ["blind", "lantern", "upper", "whole"]) for (const [m, z0, z1] of LEVELS) {
    const src = m === "5" ? d.layers5[n] : d.pyramid[n][m];
    img(`${n}_${m}`, src[0], src[1], {minzoom:z0, maxzoom:z1, layout:{visibility: n === "blind" ? "none" : "visible"},
        paint:{"raster-resampling":"linear","raster-fade-duration":0}});
  }
  style.sources.other = {type:"geojson", data:d.other}; style.sources.zone = {type:"geojson", data:d.zone}; style.sources.points = {type:"geojson", data:d.points};
  style.layers.push({id:"other", type:"line", source:"other", layout:{visibility:"none"}, paint:{"line-color":"#A9A6A0", "line-width":0.8}});
  style.layers.push({id:"zone", type:"line", source:"zone", paint:{"line-color":"#6D6E71", "line-width":1.1, "line-dasharray":[3, 2]}});
  style.layers.push({id:"points", type:"circle", source:"points", paint:{"circle-radius":3.5, "circle-color":["case",["==",["get","own"],1],"#231F20","#6D6E71"], "circle-stroke-color":"#fff", "circle-stroke-width":1}});
  const m = new maplibregl.Map({container:"m_" + key, style, center:d.dome, zoom: key === "paris" ? 11 + dz : 11, minZoom:9, maxZoom:17.5,
    attributionControl:false, dragRotate:false, pitchWithRotate:false});
  m.addControl(new maplibregl.NavigationControl({showCompass:false}));
  m.addControl(new maplibregl.ScaleControl({unit:"metric"}));
  new maplibregl.Marker({color:"#DBBE81"}).setLngLat(d.dome).addTo(m);
  if (key === "london") for (const [k, v] of Object.entries(D.sections)) {
    const el = document.createElement("div"); el.textContent = k;
    el.style.cssText = "font:600 12px sans-serif;background:#16223D;color:#fff;border-radius:50%;width:20px;height:20px;line-height:20px;text-align:center;cursor:pointer;box-shadow:0 0 0 2px #fff";
    el.addEventListener("click", ev => { ev.stopPropagation(); const w = Math.min(600, m.getContainer().clientWidth - 70);
      new maplibregl.Popup({maxWidth: (w + 30) + "px"}).setLngLat(v.lonlat).setHTML(`<img src="${v.png[lang]}" style="width:${w}px;display:block">`).addTo(m); });
    new maplibregl.Marker({element:el}).setLngLat(v.lonlat).addTo(m);
  }
  m.on("click", e => popup(key, e));
  maps[key] = m;
}
let syncing = false;
function sync(a, b, off){ maps[a].on("zoom", () => { if (syncing) return; syncing = true; maps[b].setZoom(maps[a].getZoom() + off); syncing = false; }); }
function text(){
  const L = T[lang];
  for (const id of ["t","s","f","h_london","h_paris"]) document.getElementById(id).textContent = L[id];
  for (const id of ["zone","other","whole","upper","lantern","blind","base","hint"]) document.getElementById("l_" + id).textContent = L[id];
  document.getElementById("n_london").innerHTML = L.n_london(D.numbers.london);
  document.getElementById("n_paris").innerHTML = L.n_paris(D.numbers.paris);
  document.documentElement.lang = lang;
  document.getElementById("b_en").className = lang === "en" ? "on" : ""; document.getElementById("b_ru").className = lang === "ru" ? "on" : "";
}
function toggle(id, layers){ document.getElementById(id).addEventListener("change", ev => { for (const k of ["london","paris"]) for (const l of layers)
  maps[k].setLayoutProperty(l, "visibility", ev.target.checked ? "visible" : "none"); }); }
build("london"); build("paris"); loadQuery("london"); loadQuery("paris");
sync("london", "paris", dz); sync("paris", "london", -dz);
const lv = n => ["40", "20", "10", "5"].map(m => `${n}_${m}`);
toggle("c_zone", ["zone"]); toggle("c_other", ["other"]); toggle("c_whole", lv("whole")); toggle("c_upper", lv("upper"));
toggle("c_lantern", lv("lantern")); toggle("c_blind", lv("blind")); toggle("c_base", ["base"]);
document.getElementById("b_en").onclick = () => { lang = "en"; text(); }; document.getElementById("b_ru").onclick = () => { lang = "ru"; text(); };
text();
</script></body></html>
"""


def main():
    data = build()
    html = (HTML.replace("__CSS__", (VENDOR / "maplibre-gl.css").read_text())
            .replace("__JS__", (VENDOR / "maplibre-gl.js").read_text())
            .replace("__DATA__", json.dumps(data, separators=(",", ":")))
            .replace("__WHOLE__", VIS[3]).replace("__UPPER__", VIS[2]).replace("__LANTERN__", VIS[1]))
    out = HERE / "index.html"
    out.write_text(html)
    print(out, f"{out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
