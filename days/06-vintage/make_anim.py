"""Day 6: animation "Rotterdam, 14 May 1940": the city before, the fire, the ash, the rebuilding year by year.

    python make_anim.py             # -> anim_en.mp4, anim_ru.mp4 (1080 x 1350, 30 fps, H.264, no sound) + anim_cover_*.png
    python make_anim.py ru          # one language
    python make_anim.py en --stills # a few test frames to data/raw/anim_stills/

Frames are rendered in 8 parallel processes, each encoding one segment; the segments are joined without re-encoding.

Scenes: the 1940 city map with the buildings that predate 1940; 13:27-13:40 the area the city shaded as destroyed
burns; ash and the losses (Stadsarchief); 1940 -> 2026 every building standing today appears in the year BAG gives
for it, with a bar chart of buildings per year inside the fire line; the finding. The spread of the fire is an
illustration (random ignition points inside the destroyed area of the 1940 map), not a reconstruction of the raid.
Palette and type as the main map (shared/styles/nl_rotterdam.py).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import PolyCollection
from matplotlib.colors import to_rgb
from PIL import Image
from pyproj import Transformer
from scipy import ndimage as ndi
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import make_map as M                                  # noqa: E402
import make_web as W                                  # noqa: E402
from shared.styles import nl_rotterdam as R           # noqa: E402

# Day 6: the three building periods pulled apart by lightness (Masha, 06.11.2026: "very clear and readable by period").
# Worst-case CIEDE2000 between periods, paper and water, also simulated for deutan/protan vision: 12.2 (was 4.7:
# "after 1965" #D6C087 nearly vanished into the paper, ochre and brick were close). Process-local override of the
# shared nl_rotterdam palette; nothing else in the style changes.
R.PALETTE.update(spared="#7A4E12", new="#DA6A2A", built_1940="#A8977A")
P = R.PALETTE
FPS = 30
W_PX, H_PX = 1080, 1350
X0, X1, Y0, Y1 = M.X0, M.X1, M.Y0, M.Y1
CELL = 2.5                                            # metres, raster for the 1940 map and the fire
SCENES = {"before": (0.0, 2.2), "fire": (2.2, 6.0), "ash": (6.0, 8.0), "rebuild": (8.0, 22.0), "end": (22.0, 27.0)}
T0 = 1.5          # seconds cut from the start (Masha, 06.11.2026): the fire starts ~0.7 s into the video
YEAR_KNOTS = ([0.0, 0.62, 1.0], [1940, 1972, 2026])   # the first 62 % of the rebuild scene covers 1940-1972

T = {
    "en": {"title": "ROTTERDAM, 14 MAY 1940",
           "before": "The centre before the bombing: the city's map of 1940\nand the buildings that still stand today",
           "fire": "14 May 1940. Bombs from 13:27 to 13:40, then the fire",
           "ash": "258 ha in ruins · 25,000 homes and 11,000 other\nbuildings lost · 80,000 people homeless",
           "ash_src": "Stadsarchief Rotterdam",
           "rebuild": "Every building standing today, in its year of construction",
           "bars": "buildings completed per year inside the fire line",
           "key": ["before 1940, still standing", "1940–1965", "after 1965", "fire line (brandgrens)"],
           "end1": "Inside the fire line, 5% of today's\nbuildings predate 1940.",
           "end2": "A kilometre outside: 63%.",
           "end3": "Two thirds inside date from the rebuilding of 1940–1965,\nand 99% of those are not listed as heritage.",
           "src": "Data: BAG (Kadaster via PDOK), map of the destroyed area 1940 (Stadsarchief Rotterdam), brandgrens lights\n"
                  "(Gemeente Rotterdam): public domain; listed monuments: RCE (CC BY 4.0). Facts: Stadsarchief Rotterdam. Fire spread illustrative.\n"
                  "Analysis: Marija Ercegovac · #30DayMapChallenge day 6"},
    "ru": {"title": "РОТТЕРДАМ, 14 МАЯ 1940",
           "before": "Центр до бомбардировки: карта города 1940 года\nи здания, которые стоят до сих пор",
           "fire": "14 мая 1940 года. Бомбы с 13:27 до 13:40, потом пожар",
           "ash": "258 га в руинах · 25 000 жилищ и 11 000 других\nзданий уничтожено · 80 000 человек без крова",
           "ash_src": "Stadsarchief Rotterdam",
           "rebuild": "Каждое нынешнее здание в год его постройки",
           "bars": "зданий построено за год внутри линии пожара",
           "key": ["до 1940, стоит сейчас", "1940–1965", "после 1965", "линия пожара (brandgrens)"],
           "end1": "Внутри линии пожара до 1940 года\nпостроены 5% нынешних зданий.",
           "end2": "В километре снаружи — 63%.",
           "end3": "Две трети зданий внутри — восстановление 1940–1965 годов,\nи 99% из них не охраняются как наследие.",
           "src": "Данные: BAG (Kadaster через PDOK), карта разрушений 1940 (Stadsarchief Rotterdam), светильники brandgrens\n"
                  "(Gemeente Rotterdam): общ. достояние; памятники: RCE (CC BY 4.0). Факты: Stadsarchief Rotterdam. Огонь условный.\n"
                  "Расчёт: Мария Эрцеговац · #30DayMapChallenge день 6"},
}


def ease(x):
    x = np.clip(x, 0, 1)
    return x * x * (3 - 2 * x)


def scene_t(t, name):
    a, b = SCENES[name]
    return (t - a) / (b - a)


def rgb(c):
    return np.array(to_rgb(c))


# --------------------------------------------------------------------------- data

def prepare():
    b, water, zone, line, lights = M.load()
    b = b.cx[X0 - 50:X1 + 50, Y0 - 50:Y1 + 50].reset_index(drop=True)
    Z = unary_union(zone.geometry.values)
    rp = b.geometry.representative_point()
    inside = rp.within(Z).values
    polys, years = [], []
    for geom, y in zip(b.geometry, b["bouwjaar"].astype(int)):
        for p in getattr(geom, "geoms", [geom]):
            polys.append(np.asarray(p.exterior.coords)[:, :2])
            years.append(y)
    years = np.array(years)
    inside_p = np.repeat(inside, [len(getattr(g, "geoms", [g])) for g in b.geometry])
    # the 1940 map on a 5 m grid over the frame: image, destroyed mask
    g = W.georef_1940()
    cls = W.classes_1940(g)
    nx, ny = int((X1 - X0) / CELL), int((Y1 - Y0) / CELL)
    gx = X0 + (np.arange(nx) + 0.5) * CELL
    gy = Y1 - (np.arange(ny) + 0.5) * CELL
    GX, GY = np.meshgrid(gx, gy)
    mx, my = Transformer.from_crs(28992, 3857, always_xy=True).transform(GX.ravel(), GY.ravel())
    u = (g["cu"][0] + g["cu"][1] * mx + g["cu"][2] * my).reshape(ny, nx)
    v = (g["cv"][0] + g["cv"][1] * mx + g["cv"][2] * my).reshape(ny, nx)
    img = np.asarray(g["im"]).astype(float) / 255
    # the 1940 plan as a line drawing: only the dark ink (streets, block outlines, names), not the orange shading,
    # so the "before" scene does not give away the destroyed area. Ink is taken at the scan's own resolution and
    # thickened by one pixel, so thin lines survive the resampling.
    lum = img @ np.array([0.299, 0.587, 0.114])
    ink_src = ndi.grey_dilation(np.clip((0.68 - lum) / 0.22, 0, 1), size=(2, 2))
    ink = ndi.map_coordinates(ink_src, [v, u], order=1, mode="constant")
    # the pre-war blocks of the destroyed area exactly as shaded on the 1940 map (streets stay open)
    blocks = ndi.map_coordinates((cls == 1).astype(float), [v, u], order=1, mode="constant")
    destroyed = ndi.map_coordinates((cls == 1).astype(float), [v, u], order=0, mode="constant") > 0.5
    destroyed = ndi.binary_opening(destroyed, iterations=1)
    # water today, rasterised for a soft fade-in
    from rasterio import features
    from rasterio.transform import from_origin
    wmask = features.rasterize([(water, 1)], out_shape=(ny, nx), transform=from_origin(X0, Y1, CELL, CELL)) > 0
    # illustrative fire: ignition time from random seeds inside the destroyed area, with noise
    rng = np.random.default_rng(14051940)
    ys, xs = np.nonzero(destroyed)
    pick = rng.choice(len(ys), 40, replace=False)
    seeds = np.zeros_like(destroyed)
    seeds[ys[pick], xs[pick]] = True
    dist = ndi.distance_transform_edt(~seeds) * CELL
    noise = ndi.gaussian_filter(rng.normal(0, 1, destroyed.shape), 12)
    noise = (noise - noise.min()) / (noise.max() - noise.min())
    ign = dist / np.percentile(dist[destroyed], 97) * 0.75 + noise * 0.25        # 0..~1 within the fire scene
    flicker = ndi.gaussian_filter(rng.normal(0, 1, (8,) + destroyed.shape), (0, 2.4, 2.4))
    bars_years = years[inside_p]
    st = json.loads((M.DATA / "stats.json").read_text())
    return dict(polys=polys, years=years, inside=inside_p, ink=ink, blocks=blocks, destroyed=destroyed, water=wmask,
                ign=ign, flicker=flicker, line=line, bars=bars_years, stats=st)


# --------------------------------------------------------------------------- frames

class Anim:
    def __init__(self, lang, D):
        self.t, self.D, self.lang = T[lang], D, lang
        R.apply()
        self.fig = plt.figure(figsize=(W_PX / 100, H_PX / 100), dpi=100)
        self.fig.patch.set_facecolor(P["paper"])
        f = lambda role, size: R.font(role, lang, size)                      # noqa: E731
        self.f = f
        # map band between the title and the bar chart; the frame is cropped vertically to its aspect
        self.mb = (0.235, 0.625)
        half = (X1 - X0) * self.mb[1] * H_PX / W_PX / 2
        cy = (Y0 + Y1) / 2
        self.ax = self.fig.add_axes([0, self.mb[0], 1, self.mb[1]])
        self.ax.set_xlim(X0, X1)
        self.ax.set_ylim(cy - half, cy + half)
        self.ax.set_axis_off()
        mid_y = self.mb[0] + self.mb[1] / 2
        ext = [X0, X1, Y0, Y1]
        self.base = self.ax.imshow(np.zeros(D["destroyed"].shape + (3,)), extent=ext, zorder=1, interpolation="bilinear")
        self.over = self.ax.imshow(np.zeros(D["destroyed"].shape + (4,)), extent=ext, zorder=2, interpolation="bilinear")
        self.coll = PolyCollection(D["polys"], closed=True, zorder=3, linewidths=0.25)
        self.ax.add_collection(self.coll)
        self.lines = []
        for lw, col in ((4.2, P["fire_casing"]), (2.6, P["fire"])):
            self.lines.append(self.ax.plot([], [], color=col, lw=lw, zorder=5, solid_capstyle="round")[0])
        segs_x, segs_y = [], []
        for geom in D["line"].geometry:
            for part in getattr(geom, "geoms", [geom]):
                x, y = part.xy
                segs_x += list(x) + [np.nan]
                segs_y += list(y) + [np.nan]
        self.line_xy = (segs_x, segs_y)
        # texts
        self.title = self.fig.text(0.05, 0.972, self.t["title"], fontproperties=f("title", 34), color=P["text"], va="top")
        self.caption = self.fig.text(0.05, 0.918, "", fontproperties=f("subtitle", 23), color=P["text"], va="top",
                                     linespacing=1.3)
        self.big = self.fig.text(0.95, 0.972, "", fontproperties=f("title", 60), color=P["new"], va="top", ha="right")
        box = dict(boxstyle="square,pad=0.7", facecolor="#2b241a", edgecolor="none", alpha=0)
        self.mid = self.fig.text(0.5, mid_y + 0.02, "", fontproperties=f("subtitle", 30), color=P["paper"], ha="center",
                                 va="center", linespacing=1.4, zorder=10, bbox=dict(box))
        self.mid_src = self.fig.text(0.5, mid_y - 0.075, "", fontproperties=f("body", 18), color=P["paper"],
                                     ha="center", va="center", zorder=10, bbox=dict(box))
        self.src = self.fig.text(0.05, 0.010, self.t["src"], fontproperties=f("body", 11.5), color=P["muted"], va="bottom",
                                 linespacing=1.35)
        # bar chart of buildings per year inside the line
        self.bx = self.fig.add_axes([0.07, 0.090, 0.86, 0.080])
        yrs = np.arange(1940, 2027)
        cnt = np.array([(D["bars"] == y).sum() for y in yrs])
        self.yrs, self.cnt = yrs, cnt
        self.bar = self.bx.bar(yrs, cnt, width=0.85, color=[P["new"] if y <= 1965 else P["built_1940"] for y in yrs],
                               edgecolor="none")
        self.bx.set_xlim(1939, 2027)
        self.bx.set_ylim(0, cnt.max() * 1.15)
        for s in ("top", "right", "left"):
            self.bx.spines[s].set_visible(False)
        self.bx.spines["bottom"].set_color(P["text"])
        self.bx.set_yticks([])
        self.bx.set_xticks([1940, 1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020])
        self.bx.tick_params(axis="x", colors=P["text"], labelsize=14, length=4)
        for lab in self.bx.get_xticklabels():
            lab.set_fontproperties(f("label", 14))
        self.bx.set_facecolor("none")
        self.bx_title = self.fig.text(0.07, 0.178, self.t["bars"].upper(), fontproperties=f("legend", 14), color=P["text"])
        # key under the map: always on, the colours mean the same in every scene
        import matplotlib.patches as mpatch
        import matplotlib.lines as mlines
        x, yk = 0.05, 0.208
        for col, lab in zip([P["spared"], P["new"], P["built_1940"]], self.t["key"][:3]):
            self.fig.add_artist(mpatch.Rectangle((x, yk - 0.008), 0.026, 0.016, transform=self.fig.transFigure, facecolor=col,
                                                 edgecolor=P["line"], lw=0.6))
            tx = self.fig.text(x + 0.034, yk, lab, fontproperties=f("legend", 15), color=P["text"], va="center")
            self.fig.canvas.draw() if not hasattr(self, "_r") else None
            self._r = True
            x += 0.034 + tx.get_window_extent(self.fig.canvas.get_renderer()).width / W_PX + 0.03
        for lw, col in ((5.2, P["fire_casing"]), (3.2, P["fire"])):
            self.fig.add_artist(mlines.Line2D([x, x + 0.03], [yk, yk], color=col, lw=lw, transform=self.fig.transFigure,
                                              solid_capstyle="round"))
        self.fig.text(x + 0.04, yk, self.t["key"][3], fontproperties=f("legend", 15), color=P["text"], va="center")
        # colours per polygon
        y = D["years"]
        self.col_old = np.tile(np.r_[rgb(P["spared"]), 1], (len(y), 1))
        cls_col = np.where((y >= 1940)[:, None] & (y <= 1965)[:, None], rgb(P["new"]), rgb(P["built_1940"]))
        self.col_new = np.c_[cls_col, np.ones(len(y))]
        self.edge = np.r_[rgb(P["line"]), 1]

    def year_at(self, t):
        x = scene_t(t, "rebuild")
        return float(np.interp(np.clip(x, 0, 1), *YEAR_KNOTS))

    def frame(self, t):
        D, tt = self.D, self.t
        paper = rgb(P["paper"])
        # the pre-war blocks of the centre (shaded as destroyed on the 1940 map) as built-up, the plan's lines on top
        bu = D["blocks"][..., None] * 0.65
        old_map = paper * (1 - bu) + rgb("#C99A55") * bu
        ink = D["ink"][..., None] * 0.8
        old_map = old_map * (1 - ink) + rgb(P["line"]) * ink
        y_now = self.year_at(t)
        # base layer: the 1940 map until the rebuild, fading to paper as the rubble is cleared (1940-1952)
        clear = ease((y_now - 1940) / 12) if t >= SCENES["rebuild"][0] else 0.0
        base = old_map                                       # no fade-in: frame 0 is the feed thumbnail
        base = base * (1 - clear) + paper * clear
        water = rgb(P["water"])
        wfade = ease((y_now - 1944) / 10) if t >= SCENES["rebuild"][0] else 0.0
        base = np.where(D["water"][..., None], base * (1 - wfade) + water * wfade, base)
        self.base.set_data(np.clip(base, 0, 1))
        # fire and ash overlay on the destroyed area
        ov = np.zeros(D["destroyed"].shape + (4,))
        if t >= SCENES["fire"][0]:
            ft = scene_t(t, "fire") * 1.25                                    # 0..1.25 over the fire scene
            burn = np.clip((ft - D["ign"]) / 0.22, 0, 1) * D["destroyed"]      # 0 not yet, 0-1 burning, 1 burnt
            fl = D["flicker"][int(t * 12) % len(D["flicker"])]
            fl = (fl - fl.min()) / (fl.max() - fl.min() + 1e-9)
            flame = np.clip(1 - np.abs(burn - 0.45) / 0.45, 0, 1) * (0.75 + 0.25 * fl)
            hot = np.array([1.0, 0.86, 0.35]) * flame[..., None] + np.array([0.86, 0.32, 0.08]) * (1 - flame[..., None])
            ash = np.array([0.24, 0.20, 0.15])
            col = np.where((burn >= 1)[..., None], ash, hot)
            alpha = np.clip(burn * 1.6, 0, 1) * 0.92
            if t >= SCENES["rebuild"][0]:
                alpha = alpha * (1 - clear)
            ov[..., :3] = col
            ov[..., 3] = alpha
        self.over.set_data(ov)
        # buildings
        y = D["years"]
        face = np.zeros((len(y), 4))
        old = y < 1940
        face[old] = self.col_old[old]
        if t >= SCENES["rebuild"][0]:
            built = (~old) & (y <= y_now)
            age = np.clip((y_now - y) / 2.0, 0, 1)                             # a fresh building flashes for ~2 years
            flash = (1 - age)[:, None] * np.r_[rgb(P["fire"]), 0] + age[:, None] * self.col_new[:, :]
            flash[:, 3] = 1
            face[built] = flash[built]
        edge = np.tile(self.edge, (len(y), 1))
        edge[:, 3] = (face[:, 3] > 0) * 0.8
        self.coll.set_facecolors(face)
        self.coll.set_edgecolors(edge)
        # the brandgrens: drawn from the fire scene on, over everything on the map
        show_line = t >= SCENES["fire"][0] + 0.5
        for ln in self.lines:
            ln.set_data(*self.line_xy) if show_line else ln.set_data([], [])
        # texts
        if t < SCENES["fire"][0]:
            self.caption.set_text(tt["before"])
            self.big.set_text("1940")
        elif t < SCENES["ash"][0]:
            self.caption.set_text(tt["fire"])
            mins = 27 + int(13 * np.clip(scene_t(t, "fire") * 1.6, 0, 1))
            self.big.set_text(f"13:{mins:02d}")
        elif t < SCENES["rebuild"][0]:
            self.caption.set_text(tt["fire"])
            self.big.set_text("13:40")
        else:
            self.caption.set_text(tt["rebuild"])
            self.big.set_text(f"{int(min(y_now, 2026))}")
        # the losses, over the ash
        a_mid = ease(scene_t(t, "ash") * 3) * (1 - ease((t - SCENES["rebuild"][0]) / 0.6)) if t >= SCENES["ash"][0] else 0
        self.mid.set_text(tt["ash"])
        self.mid.set_alpha(a_mid)
        self.mid.get_bbox_patch().set_alpha(0.82 * a_mid)
        self.mid_src.set_text(tt["ash_src"])
        self.mid_src.set_alpha(a_mid)
        self.mid_src.get_bbox_patch().set_alpha(0.82 * a_mid)
        # end: the finding in a box
        if t >= SCENES["end"][0]:
            a = ease((t - SCENES["end"][0]) / 0.8)
            self.mid.set_text(f"{tt['end1']}\n{tt['end2']}")
            self.mid.set_fontproperties(self.f("subtitle", 28))
            self.mid.set_color(P["text"])
            self.mid.set_bbox(dict(boxstyle="square,pad=0.8", facecolor=P["legend_paper"], edgecolor=P["text"], lw=1.2,
                                   alpha=a))
            self.mid.set_alpha(a)
            self.mid_src.set_text(tt["end3"])
            self.mid_src.set_fontproperties(self.f("body", 19))
            self.mid_src.set_color(P["text"])
            self.mid_src.set_position((0.5, self.mid.get_position()[1] - 0.14))
            self.mid_src.set_bbox(dict(boxstyle="square,pad=0.6", facecolor=P["legend_paper"], edgecolor="none", alpha=a))
            self.mid_src.set_alpha(a)
        # bars grow with the year; the chart appears with the rebuilding
        on = t >= SCENES["rebuild"][0]
        self.bx.set_visible(on)
        self.bx_title.set_visible(on)
        for rect, yr, c in zip(self.bar, self.yrs, self.cnt):
            rect.set_height(c if (t >= SCENES["rebuild"][0] and yr <= y_now) else 0)
        return self.fig

    def stills(self, folder):
        Path(folder).mkdir(parents=True, exist_ok=True)
        for sec in (0.0, 1.5, 3.4, 4.6, 7.2, 10.0, 14.0, 19.0, 23.0, 26.5):
            self.frame(sec).savefig(Path(folder) / f"{self.lang}_{sec:05.1f}.png", dpi=100)

    def segment(self, i0, i1, out):
        """Frames i0..i1-1 piped straight into an H.264 segment."""
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W_PX}x{H_PX}",
               "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "slow", "-tune", "animation",
               "-g", str(FPS * 2), "-threads", "1", str(out)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        for i in range(i0, i1):
            self.frame(i / FPS)
            self.fig.canvas.draw()
            proc.stdin.write(np.asarray(self.fig.canvas.buffer_rgba()).tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed on segment {out}")


def _worker(args):
    lang, i0, i1, out = args
    A = Anim(lang, _worker.D)
    A.segment(i0, i1, out)
    return out


def _init(D):
    _worker.D = D


def render(lang, D, jobs=8):
    """Split the frames into `jobs` segments rendered in parallel, then concatenate them without re-encoding."""
    import multiprocessing as mp
    import tempfile
    n = int(SCENES["end"][1] * FPS)
    cuts = np.linspace(int(T0 * FPS), n, jobs + 1).astype(int)
    tmp = Path(tempfile.mkdtemp(prefix="anim_", dir=M.RAW))
    parts = [(lang, int(a), int(b), tmp / f"part_{k:02d}.mp4") for k, (a, b) in enumerate(zip(cuts[:-1], cuts[1:]))]
    ctx = mp.get_context("fork")
    with ctx.Pool(jobs, initializer=_init, initargs=(D,)) as pool:
        for done in pool.imap_unordered(_worker, parts):
            print("  segment", Path(done).name, flush=True)
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p[3]}'\n" for p in parts))
    out = HERE / f"anim_{lang}.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy",
                    "-movflags", "+faststart", str(out)], check=True)
    for p in parts:
        p[3].unlink()
    lst.unlink()
    tmp.rmdir()
    print("->", out)
    return out


def cover(lang, D, sec=4.0):
    """A still for the platforms' custom thumbnail: the fire at its height."""
    A = Anim(lang, D)
    out = HERE / f"anim_cover_{lang}.png"
    A.frame(sec).savefig(out, dpi=100)
    print("->", out)


def main():
    langs = [a for a in sys.argv[1:] if a in T] or ["en", "ru"]
    D = prepare()
    for lang in langs:
        if "--stills" in sys.argv:
            Anim(lang, D).stills(M.RAW / "anim_stills")        # test frames stay out of git
        else:
            render(lang, D)
            cover(lang, D)


if __name__ == "__main__":
    main()
