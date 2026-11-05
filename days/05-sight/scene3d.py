"""Day 5 video in 3D (Masha, 04.11.2026: the flat radar video is too weak). A close-up of St Paul's, the City and the river
as a white card model from the 1 m LiDAR (fetch_closeup.py); in blue, the open ground the dome is actually visible from
(the 5 m result of sight.py, drawn on the 1 m open ground); in grey, the protected LVMF views arriving from the hills as
thin sheets from each viewpoint's eye to the base and the cross of the dome. Rendered with VTK (pyvista, off-screen);
text drawn over the frames with PIL in Source Sans 3.

    python3 -m venv --system-site-packages .venv3d && .venv3d/bin/pip install pyvista     # once (pyvista 0.49, VTK 9.7)
    python fetch_closeup.py                    # once: 1 m DSM and DTM of the close-up
    .venv3d/bin/python scene3d.py still        # test frame -> frames3d/still.png

forge3d's path tracer (used for the Belgrade renders) was tried first: on this Mac it raises on most frames
(accumulation frame count off by one to three), so the video uses VTK rasterisation with SSAO instead.
"""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image, ImageDraw, ImageFont
from rasterio.features import rasterize

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "paris"))
sys.path.insert(0, str(HERE.parents[1] / "shared"))
import pyvista as pv             # noqa: E402
import public_space as PS        # noqa: E402
import sight as L                # noqa: E402

pv.OFF_SCREEN = True
FONTS = HERE.parents[1] / "shared" / "styles" / "fonts" / "sourcesans3"
OUT = HERE / "frames3d"
BOX = (530400, 180200, 533600, 182200)            # BNG, the 1 m close-up (fetch_closeup.py)
CX, CY = (BOX[0] + BOX[2]) / 2, (BOX[1] + BOX[3]) / 2
COL = dict(ground="#DCDDDA", roof="#FAFAF8", water="#CBD7DF", park="#D6E0CD", gold="#D2A955", law="#5E6062")
# anti-AI audit (CLAUDE.md, 04.11.2026): one flat background, no gradient sky and no white fade bands (craft R1); text sits in
# flat bands above and below the 3D view, which renders at VIEW; the series signature in JetBrains Mono at the shared spot
BG, FRAME, VIEW, TOP = "#F4F4F2", (1920, 1080), (1920, 820), 140
MONO = HERE.parents[1] / "shared" / "styles" / "fonts" / "jetbrainsmono" / "JetBrainsMono-Regular.ttf"


def rgb8(h):
    return np.array([int(h[i:i + 2], 16) for i in (1, 3, 5)], np.uint8)


def P(e, n, z):
    return (e - CX, n - CY, z)


def scene(step=1):
    """Arrays of the close-up at `step` metres: heights, colours, and what the overlays need."""
    with rasterio.open(L.RAW / "closeup_dsm_1m.tif") as d:
        dsm = d.read(1)[::step, ::step].astype(np.float64)
    with rasterio.open(L.RAW / "closeup_dtm_1m.tif") as d:
        dtm = d.read(1)[::step, ::step].astype(np.float64)
    dsm = np.maximum(dsm, dtm)
    h, w = dsm.shape
    T1 = rasterio.transform.from_origin(BOX[0], BOX[3], step, step)
    open1 = (dsm - dtm) < L.OPEN_MAX
    water = rasterize([(g, 1) for g in L.water().geometry], out_shape=(h, w), transform=T1, fill=0).astype(bool)
    parks = __import__("geopandas").read_file(L.RAW / "os_layers.gpkg", layer="parks")
    park = rasterize([(g, 1) for g in parks.geometry], out_shape=(h, w), transform=T1, fill=0).astype(bool)
    fp, _ = L.stpauls_footprint()
    cath = rasterize([(fp, 1)], out_shape=(h, w), transform=T1, fill=0).astype(bool)
    # the 5 m result, looked up at every display cell centre
    open5, T5, *_ = PS.london_open()
    with rasterio.open(L.DER / "visible_level.tif") as d:
        lev5 = d.read(1)
    rr, cc = np.mgrid[0:h, 0:w]
    e, n = BOX[0] + (cc + 0.5) * step, BOX[3] - (rr + 0.5) * step
    c5, r5 = ((e - T5.c) / T5.a).astype(int), ((n - T5.f) / T5.e).astype(int)
    lv, op5 = lev5[r5, c5], open5[r5, c5]
    cls = np.where((lv != 255) & op5 & (open1 | water), L.CLASS_OF_LEVEL[np.minimum(lv, 6)], 0)
    vis = {k: (np.array(c) * 255 + 0.5).astype(np.uint8) for (k, j), c in PS.class_share_colours().items() if j == len(PS.SAT) - 1}
    rgb = np.empty((h, w, 3), np.uint8)
    rgb[:] = rgb8(COL["ground"])
    rgb[~open1] = rgb8(COL["roof"])
    rgb[park & open1] = rgb8(COL["park"])
    rgb[water] = rgb8(COL["water"])
    for k in (1, 2, 3):
        rgb[cls == k] = vis[k]
    rgb[cath] = rgb8(COL["gold"])
    st = json.loads((L.DER / "stats.json").read_text())
    dist = np.hypot(e - st["dome_axis_bng"][0], n - st["dome_axis_bng"][1])
    return dict(dsm=dsm, dtm=dtm, rgb=rgb, cls=cls, dist=dist, step=step, axis=st["dome_axis_bng"], ground=st["ground_m_aod"],
                open5=open5, T5=T5, dtm5=PS.london_open()[3], lvmf=L.lvmf())


def mesh(S):
    h, w = S["dsm"].shape
    xs = BOX[0] - CX + S["step"] * (np.arange(w) + 0.5)
    ys = BOX[3] - CY - S["step"] * (np.arange(h) + 0.5)
    X, Y = np.meshgrid(xs, ys)
    g = pv.StructuredGrid(X.astype(np.float32), Y.astype(np.float32), S["dsm"].astype(np.float32))
    g.point_data["rgb"] = S["rgb"].transpose(1, 0, 2).reshape(-1, 3)      # pyvista orders structured points column-major
    return g


def view_sheets(S):
    """One thin triangle per protected St Paul's view: from the viewpoint's eye to the base (53 m) and the cross (111 m) of
    the dome, clipped to the close-up box (the far end of each sheet lies kilometres away on its hill)."""
    g = S["lvmf"]
    pts = L.places(g)
    pts = pts[pts.stpauls]
    ax, ay = S["axis"]
    out = []
    for _, p in pts.iterrows():
        x, y = p.geometry.x, p.geometry.y
        c, r = ~S["T5"] * (x, y)
        eye = float(S["dtm5"][int(r), int(c)]) + L.EYE
        # where the line from the eye to the dome enters the box
        d = np.array([ax - x, ay - y]); D = np.hypot(*d)
        ts = [0.0]
        for k, (lo, hi) in enumerate(((BOX[0], BOX[2]), (BOX[1], BOX[3]))):
            for b in (lo, hi):
                if d[k] != 0:
                    t = (b - (x, y)[k]) / d[k]
                    q = np.array([x, y]) + t * d
                    if 0 <= t <= 1 and BOX[0] - 1e-6 <= q[0] <= BOX[2] + 1e-6 and BOX[1] - 1e-6 <= q[1] <= BOX[3] + 1e-6:
                        ts.append(t)
        t0 = max(ts) if not (BOX[0] <= x <= BOX[2] and BOX[1] <= y <= BOX[3]) else 0.0
        base, cross = S["ground"] + 53, S["ground"] + 111
        za0, zc0 = eye + (base - eye) * t0, eye + (cross - eye) * t0
        e0, n0 = x + d[0] * t0, y + d[1] * t0
        out.append(dict(name=p.get("label", ""), view=p["view"], D=D, t0=t0, poly=np.array([P(e0, n0, za0), P(ax, ay, base), P(ax, ay, cross), P(e0, n0, zc0)])))
    return out


def plotter(S, w=1920, h=1080, grid=None):
    pl = pv.Plotter(off_screen=True, window_size=(w, h), lighting="none")
    pl.set_background(BG)
    pl.add_mesh(grid if grid is not None else mesh(S), scalars="rgb", rgb=True, ambient=0.34, diffuse=0.78, specular=0.0, name="city")
    az, el = np.radians(225), np.radians(36)
    sd = np.array([np.sin(az) * np.cos(el), np.cos(az) * np.cos(el), np.sin(el)])
    for pos, it in ((sd, 0.95), (np.array([-sd[0], -sd[1], 0.9]), 0.32)):
        lt = pv.Light(position=tuple(pos * 30000), focal_point=(0, 0, 0), intensity=it, light_type="scene light")
        lt.positional = False
        pl.add_light(lt)
    pl.enable_ssao(radius=6.0, bias=0.2, kernel_size=64, blur=True)
    pl.enable_anti_aliasing("ssaa")
    return pl


def orbit(pl, S, azimuth, elevation, distance, look_z=40.0, fov=32.0, focal=None):
    ax, ay = focal if focal is not None else S["axis"]
    a, e = np.radians(azimuth), np.radians(elevation)
    v = np.array([np.sin(a) * np.cos(e), np.cos(a) * np.cos(e), np.sin(e)])
    focal = np.array(P(ax, ay, look_z))
    pl.camera_position = [tuple(focal + v * distance), tuple(focal), (0, 0, 1)]
    pl.camera.view_angle = fov
    pl.camera.clipping_range = (20, 60000)


def font(size, weight="Regular"):
    return ImageFont.truetype(str(FONTS / f"SourceSans3-{weight}.ttf"), size)


def still():
    OUT.mkdir(exist_ok=True)
    S = scene(step=1)
    pl = plotter(S)
    for sh in view_sheets(S):
        faces = np.hstack([[4, 0, 1, 2, 3]])
        poly = pv.PolyData(sh["poly"], faces)
        pl.add_mesh(poly, color=COL["law"], opacity=0.22, ambient=1.0, diffuse=0.0)
        pl.add_mesh(pv.Line(sh["poly"][0], sh["poly"][1]).tube(radius=0.9), color=COL["law"], ambient=1.0, diffuse=0.0)
        pl.add_mesh(pv.Line(sh["poly"][3], sh["poly"][2]).tube(radius=0.9), color=COL["law"], ambient=1.0, diffuse=0.0)
    pl.enable_depth_peeling(number_of_peels=6)
    orbit(pl, S, azimuth=200, elevation=28, distance=2300)
    pl.screenshot(str(OUT / "still.png"))
    pl.close()
    print(OUT / "still.png")


FPS, SECONDS = 30, 14.0
BEATS = dict(law=(3.0, 6.0), vis=(6.5, 10.5))      # seconds: the protected views fly in, then the blue spreads from the dome


def ease(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def camera_at(t):
    u = ease(t / SECONDS)
    return dict(azimuth=150 + 95 * u, elevation=24 + 9 * u, distance=2750 - 600 * u)


def frames():
    """Raw 3D frames (no text) -> frames3d/raw/f_####.png."""
    raw = OUT / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    S = scene(step=1)
    h, w = S["dsm"].shape
    grid = mesh(S)
    full = S["rgb"]
    base = full.copy()                                       # the same city without the visibility colours
    seen = S["cls"] > 0
    water = rasterize([(g, 1) for g in L.water().geometry], out_shape=(h, w),
                      transform=rasterio.transform.from_origin(BOX[0], BOX[3], S["step"], S["step"]), fill=0).astype(bool)
    base[seen] = rgb8(COL["ground"])
    base[seen & water] = rgb8(COL["water"])
    rmax = float(S["dist"][seen].max()) + 50
    pl = plotter(S, *VIEW, grid=grid)
    sheets = []
    for sh in view_sheets(S):
        q = sh["poly"].copy()
        poly = pv.PolyData(q.copy(), np.hstack([[4, 0, 1, 2, 3]]))
        edge = pv.PolyData(q.copy(), lines=np.hstack([[2, 0, 1], [2, 3, 2]]))
        pl.add_mesh(poly, color=COL["law"], opacity=0.22, ambient=1.0, diffuse=0.0)
        pl.add_mesh(edge, color=COL["law"], line_width=2.0, ambient=1.0, diffuse=0.0)
        sheets.append((q, poly, edge))
    pl.enable_depth_peeling(number_of_peels=6)
    n = int(SECONDS * FPS)
    last_r = None
    for i in range(n):
        t = i / FPS
        p = ease((t - BEATS["law"][0]) / (BEATS["law"][1] - BEATS["law"][0]))
        for q, poly, edge in sheets:                         # the leading edge runs from the box edge to the dome
            pts = q.copy()
            pts[1] = q[0] + (q[1] - q[0]) * max(p, 1e-3)
            pts[2] = q[3] + (q[2] - q[3]) * max(p, 1e-3)
            poly.points = pts
            edge.points = pts
        r = ease((t - BEATS["vis"][0]) / (BEATS["vis"][1] - BEATS["vis"][0])) * rmax
        if r != last_r:
            show = seen & (S["dist"] <= r)
            img = np.where(show[..., None], full, base)
            grid.point_data["rgb"] = img.transpose(1, 0, 2).reshape(-1, 3)
            last_r = r
        orbit(pl, S, **camera_at(t))
        pl.render()
        Image.fromarray(pl.screenshot(return_img=True)).save(raw / f"f_{i:04d}.png")
        if i % 30 == 0:
            print("frame", i, "of", n, flush=True)
    pl.close()


TXT = {
    "en": dict(
        beats=[(0.0, "London protects eight views of St Paul's", "from Parliament Hill, Primrose Hill, Greenwich, Richmond and other hills (LVMF)"),
               (3.0, "London protects eight views of St Paul's", "each grey sheet runs from a protected viewpoint to the dome, from its base to the cross"),
               (6.5, "Where the dome is actually visible from", "blue: open ground with a clear line of sight to the dome, darker where more of the dome is seen"),
               (10.5, "{sees}% of the open ground sees the dome", "a third of it is the Thames; {out}% of it lies outside the protected views")],
        legend=["whole dome", "upper dome", "lantern only", "protected view (LVMF)", "St Paul's"],
        foot="LiDAR: Environment Agency composite DSM/DTM 1 m (model at 5 m), OGL v3 · LVMF protected vistas, GLA, OGL v2"),
    "ru": dict(
        beats=[(0.0, "Лондон охраняет восемь видов на собор св. Павла", "с Парламент-хилл, Примроуз-хилл, из Гринвича, Ричмонда и с других холмов (LVMF)"),
               (3.0, "Лондон охраняет восемь видов на собор св. Павла", "каждый серый лист идёт от охраняемой точки обзора к куполу, от его основания до креста"),
               (6.5, "Откуда купол виден на самом деле", "синим: открытая земля, с которой купол виден по прямой; темнее, где видно больше купола"),
               (10.5, "Купол виден с {sees}% открытой земли", "треть этого — Темза; {out}% лежит вне охраняемых видов")],
        legend=["весь купол", "верх купола", "только фонарь", "охраняемый вид (LVMF)", "собор св. Павла"],
        foot="LiDAR: Environment Agency, DSM/DTM 1 м (модель 5 м), OGL v3 · LVMF, GLA, OGL v2"),
}
HOLD = 1.5                                            # seconds on the last frame


def overlay(img, t, lang, nums):
    """The 3D view between two flat bands: title and line on top, legend, sources and the series signature below. Text
    crossfades over 0.4 s at each beat; nothing is drawn over the model."""
    from styles.common import SIGNATURE, SIG_X, SIG_Y
    T = TXT[lang]
    W, H = FRAME
    im = Image.new("RGBA", FRAME, BG)
    im.paste(img.convert("RGBA"), (0, TOP))
    d = ImageDraw.Draw(im)
    x0 = round(SIG_X * W)
    starts = [b[0] for b in T["beats"]] + [1e9]
    for k, (t0, title, sub) in enumerate(T["beats"]):
        t1 = starts[k + 1]
        al = min(ease((t - t0) / 0.4) if k else 1.0, 1 - ease((t - t1) / 0.4) if t1 < 1e8 else 1.0)
        if al <= 0:
            continue
        same_prev = k and T["beats"][k - 1][1] == title
        same_next = k + 1 < len(T["beats"]) and T["beats"][k + 1][1] == title
        at = 1.0 if (same_prev and t < t0 + 0.4) else al
        if same_next and t >= t1:
            at = 0.0
        layer = Image.new("RGBA", FRAME, (0, 0, 0, 0))
        dl = ImageDraw.Draw(layer)
        dl.text((x0, 28), title.format(**nums), font=font(50, "Semibold"), fill=(22, 34, 61, int(255 * at)))
        dl.text((x0 + 2, 92), sub.format(**nums), font=font(28), fill=(62, 68, 76, int(255 * al)))
        im = Image.alpha_composite(im, layer)
    layer = Image.new("RGBA", FRAME, (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)
    vis = {k: tuple(int(v * 255 + 0.5) for v in c) for (k, j), c in PS.class_share_colours().items() if j == len(PS.SAT) - 1}
    items = [(vis[3], 0, BEATS["vis"][0]), (vis[2], 1, BEATS["vis"][0]), (vis[1], 2, BEATS["vis"][0]),
             (tuple(rgb8(COL["law"])), 3, BEATS["law"][0]), (tuple(rgb8(COL["gold"])), 4, 0.0)]
    x, y = x0, TOP + VIEW[1] + 32
    for col, i, ts in items:
        al = ease((t - ts) / 0.5) if ts > 0 else 1.0
        lab = T["legend"][i]
        if al > 0:
            if i == 3:
                dl.rectangle([x, y - 9, x + 30, y + 9], fill=col + (int(80 * al),), outline=col + (int(255 * al),), width=2)
            else:
                dl.rectangle([x, y - 9, x + 30, y + 9], fill=col + (int(255 * al),))
            dl.text((x + 40, y), lab, font=font(24), fill=(35, 31, 32, int(255 * al)), anchor="lm")
        x += 40 + dl.textlength(lab, font=font(24)) + 34
    dl.text((x0, H - 52), T["foot"], font=font(18), fill=(109, 110, 113, 255), anchor="ls")
    sig = SIGNATURE.format(nn="05", theme="Senses: Sight")
    dl.text((x0, H - round(SIG_Y * H)), sig, font=ImageFont.truetype(str(MONO), 18), fill=(109, 110, 113, 255), anchor="ls")
    return Image.alpha_composite(im, layer).convert("RGB")


def video(lang):
    import imageio.v2 as imageio
    st = json.loads((L.DER / "stats.json").read_text())
    f2 = (lambda v: f"{v:.1f}".replace(".", "," if lang == "ru" else "."))
    nums = dict(sees=f2(100 * st["sees_any_km2"] / st["open_ground_km2"]), out=f"{100 * st['sees_any_outside_vc_share']:.0f}")
    raw = sorted((OUT / "raw").glob("f_*.png"))
    out = HERE / "video" / f"story3d_{lang}.mp4"
    wr = imageio.get_writer(out, fps=FPS, codec="libx264", quality=None, macro_block_size=8,
                            ffmpeg_params=["-crf", "19", "-pix_fmt", "yuv420p", "-movflags", "+faststart"])
    for i, fp in enumerate(raw):
        frame = overlay(Image.open(fp), i / FPS, lang, nums)
        wr.append_data(np.asarray(frame))
        if i == len(raw) - 1:
            for _ in range(int(0.8 * FPS)):
                wr.append_data(np.asarray(frame))
        if i in (60, 150, 250, len(raw) - 1):
            frame.save(OUT / f"check_{lang}_{i:04d}.png")
    raw2 = sorted((OUT / "raw2").glob("f_*.png"))
    if raw2:                                     # part 2: the three lines of sight
        panels = Panels(lang)
        f1 = (lambda v: f"{v:.1f}".replace(".", "," if lang == "ru" else "."))
        nums2 = dict(dA=f1(panels.sec["A"]["D"] / 1000), dC=f1(panels.sec["C"]["D"] / 1000), h=f"{panels.ab['h']:.0f}")
        for i, fp in enumerate(raw2):
            t = i / FPS
            key, tl = seg_at(t)
            frame = overlay2(Image.open(fp), panels(key, tl), t, lang, nums2)
            wr.append_data(np.asarray(frame))
            if i == len(raw2) - 1:
                for _ in range(int(HOLD * FPS)):
                    wr.append_data(np.asarray(frame))
            if i in (100, 210, 330):
                frame.save(OUT / f"check2_{lang}_{i:04d}.png")
    wr.close()
    print(out)


# ---- part 2: the analytics of the detail frame inside the video. Three real lines of sight (detail.SECTIONS): A on Parliament Hill
# and B on St Pancras Way lie 6.6 and 4 km out, beyond the close-up, so the 3D view highlights their corridor (LVMF 2A.1);
# C on Waterloo Bridge lies inside the model and gets its three lines in 3D. Under the view, the section of the active line draws
# itself: terrain and buildings, then the lines to the cross, the Golden Gallery and the base of the dome, then the verdict.
VIEW2, PANEL_H = (1920, 560), 290
SEG = [("A", 0.0), ("B", 3.8), ("C", 7.6)]
SECONDS2 = 11.6
TXT2 = {
    "en": dict(title="Three real lines of sight, cut through the LiDAR",
               sub={"A": "A · Parliament Hill summit, the protected viewpoint (its corridor highlighted): {dA} km, sees the whole dome",
                    "B": "B · St Pancras Way, under the same corridor: the summit's line passes {h} m overhead, the street sees nothing",
                    "C": "C · Waterloo Bridge, no LVMF corridor: {dC} km, sees the whole dome"},
               extra={"C": "no LVMF corridor here"}),
    "ru": dict(title="Три настоящих луча зрения через поверхность LiDAR",
               sub={"A": "A · вершина Парламент-хилл, охраняемая точка (её коридор выделен): {dA} км, виден весь купол",
                    "B": "B · St Pancras Way, под тем же коридором: луч с вершины идёт в {h} м над улицей, с улицы купол не виден",
                    "C": "C · мост Ватерлоо, коридора LVMF нет: {dC} км, виден весь купол"},
               extra={"C": "коридора LVMF здесь нет"}),
}


def seg_at(t):
    k = 0
    for i, (_, t0) in enumerate(SEG):
        if t >= t0:
            k = i
    return SEG[k][0], t - SEG[k][1]


def frames2():
    """Raw 3D frames of part 2 -> frames3d/raw2/f_####.png."""
    raw = OUT / "raw2"
    raw.mkdir(parents=True, exist_ok=True)
    S = scene(step=1)
    pl = plotter(S, *VIEW2)
    navy = "#" + "".join(f"{int(v * 255 + 0.5):02X}" for v in PS.class_share_colours()[(3, len(PS.SAT) - 1)])
    hl = []
    for sh in view_sheets(S):
        q = sh["poly"]
        pl.add_mesh(pv.PolyData(q.copy(), np.hstack([[4, 0, 1, 2, 3]])), color=COL["law"], opacity=0.22, ambient=1.0, diffuse=0.0)
        pl.add_mesh(pv.PolyData(q.copy(), lines=np.hstack([[2, 0, 1], [2, 3, 2]])), color=COL["law"], line_width=2.0, ambient=1.0, diffuse=0.0)
        if sh["view"] == "2A.1":            # Parliament Hill: the corridor of A and B
            hl.append(pl.add_mesh(pv.PolyData(q.copy(), np.hstack([[4, 0, 1, 2, 3]])), color=navy, opacity=0.5, ambient=1.0, diffuse=0.0))
            hl.append(pl.add_mesh(pv.PolyData(q.copy(), lines=np.hstack([[2, 0, 1], [2, 3, 2]])), color=navy, line_width=3.5, ambient=1.0,
                                  diffuse=0.0))
    # C: the Waterloo Bridge viewer, eye on the 5 m DTM cell like the section, lines to the cross, the gallery and the base
    import detail as DT
    cx_, cy_ = DT.SECTIONS["C"]
    c5, r5 = ~S["T5"] * (cx_, cy_)
    ex, ey = S["T5"] * (int(c5) + 0.5, int(r5) + 0.5)
    eye = float(S["dtm5"][int(r5), int(c5)]) + L.EYE
    ax_, ay_ = S["axis"]
    vis = {k: "#" + "".join(f"{int(v * 255 + 0.5):02X}" for v in c) for (k, j), c in PS.class_share_colours().items() if j == len(PS.SAT) - 1}
    targets = [(S["ground"] + 111, vis[1]), (S["ground"] + 85, vis[2]), (S["ground"] + 53, vis[3])]
    tubes = [None] * 3
    marker = pl.add_mesh(pv.Sphere(radius=9, center=P(ex, ey, eye)), color="#231F20")
    pl.enable_depth_peeling(number_of_peels=6)
    n = int(SECONDS2 * FPS)
    for i in range(n):
        t = i / FPS
        key, tl = seg_at(t)
        for a in hl:
            a.visibility = key in ("A", "B")
        marker.visibility = key == "C"
        g = ease((tl - 0.5) / 1.4) if key == "C" else 0.0
        for k, (zt, col) in enumerate(targets):
            if tubes[k] is not None:
                pl.remove_actor(tubes[k])
                tubes[k] = None
            if g > 0:
                p0, p1 = np.array(P(ex, ey, eye)), np.array(P(ax_, ay_, zt))
                tubes[k] = pl.add_mesh(pv.Line(tuple(p0), tuple(p0 + (p1 - p0) * g)).tube(radius=2.6, n_sides=14), color=col,
                                       ambient=0.6, diffuse=0.5)
        u = ease(t / SECONDS2)
        fx, fy = ax_ + 0.4 * (ex - ax_), ay_ + 0.4 * (ey - ay_)      # between the dome and C, so both stay in frame
        orbit(pl, S, azimuth=196 + 26 * u, elevation=31 + 3 * u, distance=2900 - 250 * u, look_z=25, focal=(fx, fy))
        pl.render()
        Image.fromarray(pl.screenshot(return_img=True)).save(raw / f"f_{i:04d}.png")
        if i % 60 == 0:
            print("part 2 frame", i, "of", n, flush=True)
    pl.close()


class Panels:
    """The section of the active line, drawn progressively, as a 1920 x PANEL_H image (matplotlib, Source Sans 3)."""

    def __init__(self, lang):
        import matplotlib
        matplotlib.use("Agg")
        import detail as DT
        import paris_apur as PA
        self.DT, self.PA, self.lang, self.t = DT, PA, lang, DT.TXT[lang]
        Ld = DT.london()
        self.sec = {k: DT.section(Ld, xy) for k, xy in DT.SECTIONS.items()}
        self.ab = PA.section_data(DT, Ld)
        st = json.loads((L.DER / "stats.json").read_text())
        self.cor = st["public_space"]["corridors"]["2A.1"]

    def __call__(self, key, tl):
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        DT, PA, t, lang = self.DT, self.PA, self.t, self.lang
        S_, P_, VIS = PA.S, PA.P, PA.VIS
        sec = self.sec[key]
        s, km = sec["s"], sec["s"] / 1000
        D = km[-1]
        p1, p2, p3 = ease(tl / 0.9), ease((tl - 0.9) / 1.2), ease((tl - 2.1) / 0.5)
        fig = plt.figure(figsize=(19.2, PANEL_H / 100), dpi=100, facecolor=BG)
        ax = fig.add_axes([0.04 + 0.025, 0.24, 0.6, 0.64], facecolor=BG)
        show = km <= p1 * D * 1.0001
        ax.fill_between(km[show], 0, sec["dtm"][show], color=DT.GROUND, lw=0, zorder=1)
        m = show & (sec["ndsm"] > 0.5)
        ax.fill_between(km, sec["dtm"], sec["dsm"], where=m, color=DT.OBJ, lw=0, zorder=2, step="mid")
        ax.fill_between(km, sec["dtm"], sec["dsm"], where=show & sec["body"], color=DT.BODY, lw=0, zorder=2.1, step="mid")
        cols = {0: VIS[1], 2: VIS[2], 4: VIS[3]}
        reach = p2 * D
        for i in DT.SHOW:
            vis_, hit, line = sec["res"][i]
            if p2 <= 0:
                break
            if vis_:
                k = km <= reach
                ax.plot(km[k], line[k], color=cols[i], lw=2.0, zorder=4)
            else:
                stop = min(hit, int(np.searchsorted(km, reach)))
                ax.plot(km[:stop + 1], line[:stop + 1], color="#9A958C", lw=1.6, zorder=4, linestyle=(0, (3, 2)))
                if reach >= km[hit]:
                    ax.scatter([km[hit]], [line[hit]], marker="x", s=60, color=DT.BLOCK, lw=2.0, zorder=5)
                    k = (km >= km[hit]) & (km <= reach)
                    ax.plot(km[k], line[k], color="#9A958C", lw=1.0, linestyle=(0, (1, 2)), zorder=3.9)
        ax.scatter([0], [sec["eye"]], s=30, color=P_["text"], zorder=6)
        ax.set_xlim(-0.02 * D, D * 1.02)
        ax.set_ylim(0, 140)
        for sp_ in ("top", "right"):
            ax.spines[sp_].set_visible(False)
        for sp_ in ("left", "bottom"):
            ax.spines[sp_].set_color("#9A958C")
        ax.tick_params(labelsize=10, colors=P_["muted"], length=3)
        for lab in ax.get_xticklabels() + ax.get_yticklabels():
            lab.set_fontproperties(S_.font("label", lang, 10))
        ax.set_xlabel(t["xlab"], fontproperties=S_.font("label", lang, 10), color=P_["muted"], labelpad=2)
        ax.set_ylabel(t["ylab"], fontproperties=S_.font("label", lang, 10), color=P_["muted"])
        # line key along the top of the chart
        x, y = 0.01, 1.08
        for col, ls, lab in ((VIS[1], "-", t["lines"][0]), (VIS[2], "-", t["lines"][1]), (VIS[3], "-", t["lines"][2]),
                             ("#9A958C", (0, (3, 2)), t["lines"][3])):
            ax.add_artist(Line2D([x, x + 0.03], [y, y], transform=ax.transAxes, color=col, lw=2.0, linestyle=ls, clip_on=False))
            tx = ax.text(x + 0.037, y, lab, transform=ax.transAxes, fontproperties=S_.font("legend", lang, 11), color=P_["text"],
                         va="center")
            fig.canvas.draw()
            x = tx.get_window_extent(renderer=fig.canvas.get_renderer()).transformed(ax.transAxes.inverted()).x1 + 0.03
        # the verdict, right of the chart
        lc = DT.lowest_class(sec["res"])
        xr = 0.70
        fig.text(xr, 0.86, t["sec"][key], fontproperties=S_.font("label_bold", lang, 15), color=PA.P["accent3"], va="top",
                 alpha=max(p1, 0.0))
        fig.text(xr, 0.66, t["verdict"][lc], fontproperties=S_.font("title", lang, 22), color=VIS[3] if lc else DT.BLOCK, va="top",
                 alpha=p3)
        lines = [t["dist"].format(d=sec["D"] / 1000).replace(".", "," if lang == "ru" else ".")]
        if key == "B":
            hit = sec["res"][0][1]
            lines.append(t["blocked"].format(h=sec["ndsm"][hit], d=sec["s"][hit]))
            c = f"{self.cor['public_cells_3_5km']:,}".replace(",", " " if lang == "ru" else ",")
            lines.append(t["corridor0"].replace("{c:,}", c))
        if key == "C":
            lines.append(TXT2[lang]["extra"]["C"])
        fig.text(xr, 0.36, "\n".join(lines), fontproperties=S_.font("label", lang, 13), color=P_["muted"], va="top", linespacing=1.4,
                 alpha=p3)
        fig.canvas.draw()
        img = Image.frombuffer("RGBA", fig.canvas.get_width_height(), bytes(fig.canvas.buffer_rgba())).convert("RGB")
        plt.close(fig)
        return img


def overlay2(img3d, panel, t, lang, nums):
    from styles.common import SIGNATURE, SIG_X, SIG_Y
    W, H = FRAME
    im = Image.new("RGB", FRAME, BG)
    im.paste(img3d.convert("RGB"), (0, TOP))
    im.paste(panel, (0, TOP + VIEW2[1]))
    d = ImageDraw.Draw(im, "RGBA")
    x0 = round(SIG_X * W)
    key, tl = seg_at(t)
    T2 = TXT2[lang]
    d.text((x0, 28), T2["title"], font=font(50, "Semibold"), fill=(22, 34, 61, 255))
    al = 1.0 if key == "A" and t < 0.4 else ease(tl / 0.4)
    d.text((x0 + 2, 92), T2["sub"][key].format(**nums), font=font(28), fill=(62, 68, 76, int(255 * al)))
    d.line([(x0, TOP + VIEW2[1]), (W - x0, TOP + VIEW2[1])], fill=(208, 208, 208, 255), width=1)
    d.text((x0, H - 52), TXT[lang]["foot"], font=font(18), fill=(109, 110, 113, 255), anchor="ls")
    sig = SIGNATURE.format(nn="05", theme="Senses: Sight")
    d.text((x0, H - round(SIG_Y * H)), sig, font=ImageFont.truetype(str(MONO), 18), fill=(109, 110, 113, 255), anchor="ls")
    return im


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "still"
    if cmd == "video":
        for lang in (sys.argv[2:] or ["en", "ru"]):
            video(lang)
    else:
        {"still": still, "frames": frames, "frames2": frames2}[cmd]()
