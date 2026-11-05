"""Day 5 video, after the storyboard of the review: one extent per city, the same camera for both, four beats.

  1  the two cities and their domes            (1.5 s)
  2  what the law protects: corridors fade in  (2 s)
  3  where the dome is actually seen: a radar sweep reveals the 50 m overview grid, with counters  (4.5 s)
  4  zoom to the 5 m cells of the two zoom windows (3 s), then hold on the takeaway (1.5 s)

The overview colours each 50 m cell by the best part of the dome seen in it and greys it where only a small share of its
open ground sees the dome (the encoding of the main frame); the zoom shows the model's own 5 m cells. Counters are
computed on the 5 m grid. The law is a thin grey dash, as on the main frame.

    python story.py en ru       # video/story_en.mp4, video/story_ru.mp4 (1920 x 1200, 24 fps, 12.5 s)
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "paris"))
import matplotlib as mpl           # noqa: E402
mpl.use("Agg")
import detail as DT                # noqa: E402  (London arrays, class image)
import imageio.v2 as imageio       # noqa: E402
import matplotlib.pyplot as plt    # noqa: E402
import numpy as np                 # noqa: E402
import paris_apur as PA            # noqa: E402
import public_space as PS          # noqa: E402
import geopandas as gpd            # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from rasterio.features import rasterize  # noqa: E402

S, P0, L0, CLEAN, VIS, P = PA.S, PA.P0, PA.L0, PA.CLEAN, PA.VIS, PA.P
CORR, FUS, NAVY = PA.CORR, PA.FUS, P["accent3"]
FPS, W_PX, H_PX, DPI, BASE_RES = 24, 1920, 1200, 100, 6.0
BOX = {"london": [0.03, 0.2, 0.455, 0.609], "paris": [0.515, 0.2, 0.455, 0.609]}
B1, B2, B3, B4, B5 = 36, 48, 108, 72, 36            # frames per beat
TXT = {
    "en": dict(title="Where is the dome actually visible from?",
               beat=["Two cities, two domes, two laws on views", "1 · What the law protects", "2 · Where the dome is actually seen",
                     "3 · Up close: the model's 5 m cells"],
               panel={"london": "London · St Paul's Cathedral", "paris": "Paris · Sacré-Cœur"},
               law={"london": "8 protected view corridors (LVMF)", "paris": "1 protected faisceau de vues (PLU)"},
               seen="of the open ground sees the dome", inside={"london": "of that ground lies inside the corridors",
                                                                "paris": "of that ground lies inside the faisceau"},
               share_head="50 m cells: the best part of the dome seen in the cell", grey="greyer where less of the cell sees it",
               cls_head="lowest part of the dome seen", cls=["whole dome", "upper dome", "lantern only", "dome not visible"],
               take="Both laws guard a line in the sky from a few viewpoints, not the streets' view of the dome.", km="km²",
               src="Data: GLA LVMF, Environment Agency LiDAR (OGL); Ville de Paris PLU, IGN LiDAR HD (ODbL, Licence Ouverte); OSM, Overture Maps (ODbL). "
                   "Line of sight from a 1.6 m eye, 5 m cells, 22 × 18 km around each dome.",
               sign="Analysis: Marija Ercegovac · #30DayMapChallenge day 5"),
    "ru": dict(title="Откуда купол виден на самом деле?",
               beat=["Два города, два купола, два закона о видах", "1 · Что охраняет закон", "2 · Откуда купол виден на самом деле",
                     "3 · Крупно: ячейки модели, 5 м"],
               panel={"london": "Лондон · собор св. Павла", "paris": "Париж · Сакре-Кёр"},
               law={"london": "8 охраняемых коридоров вида (LVMF)", "paris": "1 охраняемый пучок видов (PLU)"},
               seen="открытой земли видят купол", inside={"london": "этой земли лежит внутри коридоров",
                                                          "paris": "этой земли лежит внутри пучка"},
               share_head="ячейки 50 м: лучшая видимая часть купола в ячейке", grey="серее, где купол видит меньшая доля ячейки",
               cls_head="нижняя видимая часть купола", cls=["весь купол", "верх купола", "только фонарь", "купол не виден"],
               take="Оба закона берегут линию в небе с нескольких точек, а не вид на купол с улиц.", km="км²",
               src="Данные: GLA LVMF, Environment Agency LiDAR (OGL); Ville de Paris PLU, IGN LiDAR HD (ODbL, Licence Ouverte); OSM, Overture Maps (ODbL). "
                   "Луч зрения от глаза на высоте 1,6 м, ячейки 5 м, 22 × 18 км вокруг каждого купола.",
               sign="Расчёт: Мария Эрцеговац · #30DayMapChallenge день 5"),
}


def ease(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * (3 - 2 * u)


def render_base(extent, draw):
    x0, x1, y0, y1 = extent
    w, h = int(round((x1 - x0) / BASE_RES)), int(round((y1 - y0) / BASE_RES))
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_axis_off()
    PA.ground(ax, CLEAN["land"])
    draw(ax)
    fig.canvas.draw()
    img = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    plt.close(fig)
    return img


def city(key, Ld, DP):
    if key == "london":
        lev, open_, T, wm = Ld["lev"], Ld["open"], Ld["T"], Ld["wm"]
        axis = Ld["axis"]
        g = Ld["g"]; zone_polys = g[(g.TYPE == "VC") & g.stpauls]
        osl = PA.OS_LAYERS
        parks, roads, rail = PA.layer(osl, "parks", 27700), PA.layer(osl, "roads", 27700), PA.layer(osl, "rail", 27700)

        def draw(ax):
            parks.plot(ax=ax, color=CLEAN["park"], lw=0); Ld["water"].plot(ax=ax, color=CLEAN["water"], lw=0)
            roads.plot(ax=ax, color=CLEAN["road"], lw=0.8); rail.plot(ax=ax, color=CLEAN["rail"], lw=0.6)
        boundary = None
    else:
        lev, open_, T, wm = DP["levs"]["sacrecoeur"], DP["open"], DP["T"], DP["water_mask"]
        axis = DP["stats"]["domes"]["sacrecoeur"]["axis_l93"]
        g = DP["g"]; zone_polys = g[g.fuseau == P0.DOMES["sacrecoeur"]["letter"]].dissolve()
        boundary = DP["boundary"]

        def draw(ax):
            DP["green"].plot(ax=ax, color=CLEAN["park"], lw=0); DP["water"].plot(ax=ax, color=CLEAN["water"], lw=0)
            DP["roads"].plot(ax=ax, color=CLEAN["road"], lw=0.8); DP["rail"].plot(ax=ax, color=CLEAN["rail"], lw=0.6)
            gpd.GeoSeries([boundary.boundary], crs=2154).plot(ax=ax, color=PA.CITY, lw=1.1)     # solid: the dash is the law
    h, w = lev.shape
    left, top = T.c, T.f
    full = (left, left + w * T.a, top + h * T.e, top)
    base = render_base(full, draw)
    share_img, share_ext, *_ = PS.class_share_rgba(lev, open_, T)
    bh, bw = share_img.shape[:2]
    jj, ii = np.meshgrid(np.arange(bw), np.arange(bh))
    cx = share_ext[0] + (jj + 0.5) * (share_ext[1] - share_ext[0]) / bw
    cy = share_ext[3] - (ii + 0.5) * (share_ext[3] - share_ext[2]) / bh
    share_ang = (np.degrees(np.arctan2(cx - axis[0], cy - axis[1])) + 360) % 360
    # 5 m class image, cropped around the final camera window
    zx0, zy0, zx1, zy1 = PS.ZOOMS[key]
    zcx, zcy = (zx0 + zx1) / 2, (zy0 + zy1) / 2
    cam_w = zx1 - zx0
    cam_h = cam_w * (BOX[key][3] * H_PX) / (BOX[key][2] * W_PX)
    m = 600
    c0, r1 = ~T * (zcx - cam_w / 2 - m, zcy - cam_h / 2 - m)
    c1, r0 = ~T * (zcx + cam_w / 2 + m, zcy + cam_h / 2 + m)
    c0, c1, r0, r1 = max(int(c0), 0), min(int(c1), w), max(int(r0), 0), min(int(r1), h)
    cls_img = (DT.class_image(lev[r0:r1, c0:c1], open_[r0:r1, c0:c1], wm[r0:r1, c0:c1]) * 255).astype(np.uint8)
    cls_ext = (left + c0 * T.a, left + c1 * T.a, top + r1 * T.e, top + r0 * T.e)
    # counters by compass angle on the 5 m grid
    rr, cc = np.nonzero((lev != 255) & open_)
    xs, ys = T * (cc + 0.5, rr + 0.5)
    ang = (np.degrees(np.arctan2(xs - axis[0], ys - axis[1])) + 360) % 360
    zone = rasterize([(geom, 1) for geom in zone_polys.geometry], out_shape=lev.shape, transform=T, fill=0).astype(bool)
    bins = np.arange(0, 360.5, 0.5)
    km2 = 25 / 1e6
    seen_cum = np.concatenate([[0], np.cumsum(np.histogram(ang, bins)[0])]) * km2
    zone_cum = np.concatenate([[0], np.cumsum(np.histogram(ang[zone[rr, cc]], bins)[0])]) * km2
    lines = []
    for geom in zone_polys.geometry:
        for part in getattr(geom, "geoms", [geom]):
            xy = np.asarray(part.exterior.coords)
            lines.append(xy)
    cam_end = (zcx - cam_w / 2, zcx + cam_w / 2, zcy - cam_h / 2, zcy + cam_h / 2)
    fx0, fx1, fy0, fy1 = full
    fh = (fx1 - fx0) * (BOX[key][3] * H_PX) / (BOX[key][2] * W_PX)
    fcy = (fy0 + fy1) / 2
    cam_start = (fx0, fx1, fcy - fh / 2, fcy + fh / 2)
    return dict(key=key, base=base, full=full, share=share_img, share_ext=share_ext, share_ang=share_ang, has=share_img[..., 3] > 0,
                cls=cls_img, cls_ext=cls_ext, axis=axis, seen_cum=seen_cum, zone_cum=zone_cum, open_km2=open_.sum() * km2,
                lines=lines, cam_start=cam_start, cam_end=cam_end, colour=PA.LAW)


def main(lang, cities):
    t = TXT[lang]
    S.apply()
    fig = plt.figure(figsize=(W_PX / DPI, H_PX / DPI), dpi=DPI)
    fig.patch.set_facecolor("#FFFFFF")
    fig.text(0.03, 0.965, t["title"], fontproperties=S.font("title", lang, 26), color=NAVY, va="top")
    beat_txt = fig.text(0.03, 0.905, "", fontproperties=S.font("label_bold", lang, 15), color=P["text"], va="top")
    A = {}
    for key, C in cities.items():
        bx = BOX[key]
        ax = fig.add_axes(bx); ax.set_xticks([]); ax.set_yticks([])
        for s_ in ax.spines.values():
            s_.set_color("#C8C6C1"); s_.set_linewidth(0.8)
        x0, x1, y0, y1 = C["full"]
        ax.imshow(C["base"], extent=C["full"], interpolation="antialiased", zorder=1)
        share = ax.imshow(np.zeros_like(C["share"]), extent=C["share_ext"], interpolation="nearest", zorder=3)
        cls = ax.imshow(C["cls"], extent=C["cls_ext"], interpolation="nearest", zorder=4, alpha=0.0)
        law = [ax.plot(xy[:, 0], xy[:, 1], color=C["colour"], lw=1.1, linestyle=PA.LAW_DASH, zorder=5, alpha=0.0)[0] for xy in C["lines"]]
        trail = ax.plot([], [], color=NAVY, lw=1.0, alpha=0.5, zorder=6)[0]
        ax.scatter([C["axis"][0]], [C["axis"][1]], s=90, facecolor=P["accent"], edgecolor=P["text"], lw=1.0, zorder=7)
        fig.text(bx[0], bx[1] + bx[3] + 0.01, t["panel"][key], fontproperties=S.font("label_bold", lang, 15), color=NAVY, va="bottom")
        law_txt = fig.text(bx[0] + bx[2], bx[1] + bx[3] + 0.01, t["law"][key], fontproperties=S.font("label", lang, 12), color=C["colour"],
                           va="bottom", ha="right", alpha=0.0)
        n1 = fig.text(bx[0], bx[1] - 0.012, "", fontproperties=S.font("title", lang, 30), color=VIS[3], va="top")
        l1 = fig.text(bx[0], bx[1] - 0.075, t["seen"], fontproperties=S.font("label", lang, 12), color=P["muted"], va="top", alpha=0.0)
        n2 = fig.text(bx[0] + 0.24, bx[1] - 0.012, "", fontproperties=S.font("title", lang, 30), color=C["colour"], va="top")
        l2 = fig.text(bx[0] + 0.24, bx[1] - 0.075, t["inside"][key], fontproperties=S.font("label", lang, 12), color=P["muted"], va="top", alpha=0.0)
        A[key] = dict(ax=ax, share=share, cls=cls, law=law, trail=trail, law_txt=law_txt, n1=n1, l1=l1, n2=n2, l2=l2)
    # legends (bottom), crossfaded
    def legend_row(y, items, head, kind):
        arts = [fig.text(0.03, y + 0.022, head, fontproperties=S.font("label", lang, 11), color=P["muted"], va="center", alpha=0.0)]
        x = 0.03
        for col, lab in items:
            r = Rectangle((x, y - 0.008), 0.022, 0.016, transform=fig.transFigure, facecolor=col, edgecolor=col, alpha=0.0)
            fig.patches.append(r); arts.append(r)
            tx = fig.text(x + 0.027, y, lab, fontproperties=S.font("legend", lang, 11), color=P["text"], va="center", alpha=0.0)
            arts.append(tx)
            fig.canvas.draw()
            x = tx.get_window_extent(renderer=fig.canvas.get_renderer()).x1 / fig.bbox.width + 0.02
        return arts
    leg_share = legend_row(0.062, [(VIS[3], t["cls"][0]), (VIS[2], t["cls"][1]), (VIS[1], t["cls"][2])], t["share_head"], "share")
    fig.canvas.draw()
    gx = leg_share[-1].get_window_extent(renderer=fig.canvas.get_renderer()).x1 / fig.bbox.width + 0.03
    cs = PS.class_share_colours()
    for j in range(3):                       # the saturation key: one class, three shares
        r = Rectangle((gx + j * 0.016, 0.054), 0.014, 0.016, transform=fig.transFigure, facecolor=cs[(2, j)], edgecolor="none", alpha=0.0)
        fig.patches.append(r); leg_share.append(r)
    leg_share.append(fig.text(gx + 3 * 0.016 + 0.006, 0.062, t["grey"] + " (≤10%, 10–50%, >50%)", fontproperties=S.font("legend", lang, 11),
                              color=P["text"], va="center", alpha=0.0))
    leg_cls = legend_row(0.062, [(VIS[3], t["cls"][0]), (VIS[2], t["cls"][1]), (VIS[1], t["cls"][2]), (DT.NOVIEW, t["cls"][3])], t["cls_head"], "cls")
    take = fig.text(0.5, 0.075, t["take"], fontproperties=S.font("label_bold", lang, 17), color=NAVY, va="center", ha="center", alpha=0.0)
    fig.text(0.03, 0.012, t["src"] + "   " + t["sign"], fontproperties=S.font("body", lang, 9), color=P["muted"], va="bottom")

    out = HERE / "video" / f"story_{lang}.mp4"
    out.parent.mkdir(exist_ok=True)
    writer = imageio.get_writer(out, fps=FPS, codec="libx264", quality=None, macro_block_size=2,
                                ffmpeg_params=["-crf", "21", "-movflags", "+faststart"])
    total = B1 + B2 + B3 + B4 + B5
    for f in range(total):
        law_a = ease((f - B1) / 24)
        sweep = ease((f - B1 - B2) / 84) * 360 if f >= B1 + B2 else 0.0
        zoom = ease((f - B1 - B2 - B3) / 54)
        fade5 = ease((f - B1 - B2 - B3 - 36) / 18)
        beat = 0 if f < B1 else 1 if f < B1 + B2 else 2 if f < B1 + B2 + B3 else 3
        beat_txt.set_text(t["beat"][beat])
        for key, C in cities.items():
            a = A[key]
            cs, ce = C["cam_start"], C["cam_end"]
            cam = [cs[i] + (ce[i] - cs[i]) * zoom for i in range(4)]
            a["ax"].set_xlim(cam[0], cam[1]); a["ax"].set_ylim(cam[2], cam[3])
            for ln in a["law"]:
                ln.set_alpha(law_a)
            a["law_txt"].set_alpha(law_a)
            img = C["share"].copy()
            img[(C["share_ang"] > sweep) | ~C["has"]] = 0
            img[..., 3] *= (1 - fade5)
            a["share"].set_data(img)
            a["cls"].set_alpha(fade5)
            on = 0 < sweep < 360
            a["trail"].set_visible(on)
            if on:
                r = 30000
                a["trail"].set_data([C["axis"][0], C["axis"][0] + r * np.sin(np.radians(sweep))],
                                    [C["axis"][1], C["axis"][1] + r * np.cos(np.radians(sweep))])
            k = int(round(sweep / 0.5))
            seen, zone = C["seen_cum"][k], C["zone_cum"][k]
            vis = f >= B1 + B2
            a["n1"].set_text(f"{L0.fmt(100 * seen / C['open_km2'], lang, 1)}%" if vis else "")
            a["n2"].set_text((f"{L0.fmt(100 * zone / seen, lang, 0)}%" if seen > 0 else "0%") if vis else "")
            a["l1"].set_alpha(1.0 if vis else 0.0); a["l2"].set_alpha(1.0 if vis else 0.0)
        for art in leg_share:
            art.set_alpha((1.0 if B1 + B2 <= f else 0.0) * (1 - fade5) * (0.0 if f >= B1 + B2 + B3 + B4 else 1.0))
        for art in leg_cls:
            art.set_alpha(fade5 * (0.0 if f >= B1 + B2 + B3 + B4 else 1.0))
        take.set_alpha(ease((f - B1 - B2 - B3 - B4) / 12))
        fig.canvas.draw()
        writer.append_data(np.asarray(fig.canvas.buffer_rgba())[..., :3].copy())
    writer.close()
    plt.close(fig)
    print(out, total / FPS, "s")


if __name__ == "__main__":
    Ld = DT.london()
    DP = PA.paris_layers()
    cities = {k: city(k, Ld, DP) for k in ("london", "paris")}
    for lang in (sys.argv[1:] or ["en", "ru"]):
        main(lang, cities)
