"""Day 5 animation: a radar sweep around each dome reveals the ground it is actually visible from.

London (St Paul's) then Paris (Sacré-Cœur), each with a running counter: open ground that sees the dome so far, and the
share of it inside the protected zones (LVMF corridors / the faisceau de vues). Ends on both numbers side by side.
Same data and clean base as the maps; the visibility is shown at 20 m (max of 4 x 4 cells of 5 m) so that thin slivers
stay visible at video size, the counters are computed on the full 5 m rasters.

    python animate.py en ru          # video/sweep_en.mp4, video/sweep_ru.mp4 (1080 x 1350, 24 fps, ~21 s)
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "paris"))
import paris_apur as PA            # noqa: E402  (layers, clean base colours, fonts)
import imageio.v2 as imageio       # noqa: E402
import matplotlib as mpl           # noqa: E402
import matplotlib.pyplot as plt    # noqa: E402
import numpy as np                 # noqa: E402
from matplotlib.patches import Rectangle, Wedge  # noqa: E402
from rasterio.features import rasterize  # noqa: E402

mpl.use("Agg")
S, P0, CLEAN, VIS, P = PA.S, PA.P0, PA.CLEAN, PA.VIS, PA.P
FPS, POOL, CELL = 24, 4, 5.0
W, H, DPI = 5.4, 6.75, 200                      # 1080 x 1350
NAVY, CORR, FUS = P["accent3"], PA.CORR, PA.FUS

TXT = {
    "en": dict(title="Where is the dome actually visible from?",
               city={"london": "London · St Paul's Cathedral", "paris": "Paris · Sacré-Cœur de Montmartre"},
               seen="open ground that sees the dome", inside={"london": "of it inside the 8 protected LVMF corridors",
                                                               "paris": "of it inside the dome's protected faisceau de vues"},
               zone={"london": "protected view corridor (LVMF)", "paris": "protected faisceau de vues (PLU)"},
               leg=["whole dome", "upper dome", "lantern only"], dome={"london": "St Paul's", "paris": "Sacré-Cœur"},
               end_title="Two laws on views, one result", end_line="share of the open ground that sees the dome",
               end_out="of that ground lies outside the protected zones",
               end_note="Both laws guard a line in the sky from a few viewpoints, not the streets' view of the dome.",
               km="km²", src="Data: GLA LVMF, Environment Agency LiDAR (OGL); Ville de Paris PLU, IGN LiDAR HD (ODbL, Licence Ouverte); "
                              "OSM, Overture Maps (ODbL).\nLine of sight from a 1.6 m eye, 5 m cells, 22 × 18 km around each dome.",
               sign="Analysis: Marija Ercegovac · #30DayMapChallenge day 5"),
    "ru": dict(title="Откуда купол виден на самом деле?",
               city={"london": "Лондон · собор св. Павла", "paris": "Париж · Сакре-Кёр на Монмартре"},
               seen="открытой земли, с которой виден купол", inside={"london": "из неё внутри 8 охраняемых коридоров LVMF",
                                                                     "paris": "из неё внутри охраняемого пучка видов"},
               zone={"london": "охраняемый коридор вида (LVMF)", "paris": "охраняемый пучок видов (PLU)"},
               leg=["весь купол", "верх купола", "только фонарь"], dome={"london": "св. Павел", "paris": "Сакре-Кёр"},
               end_title="Два закона о видах, один результат", end_line="доля открытой земли, с которой виден купол",
               end_out="этой земли лежит вне охраняемых зон",
               end_note="Оба закона берегут линию в небе с нескольких точек, а не вид на купол с улиц.",
               km="км²", src="Данные: GLA LVMF, Environment Agency LiDAR (OGL); Ville de Paris PLU, IGN LiDAR HD (ODbL, Licence Ouverte); "
                              "OSM, Overture Maps (ODbL).\nЛуч зрения от глаза на высоте 1,6 м, ячейки 5 м, 22 × 18 км вокруг каждого купола.",
               sign="Расчёт: Мария Эрцеговац · #30DayMapChallenge день 5"),
}


def fmt(x, lang, nd=1):
    s = f"{x:.{nd}f}"
    return s.replace(".", ",") if lang == "ru" else s


def london_open_float(D):
    import rasterio
    raw = HERE / "data" / "raw"
    with rasterio.open(raw / "dsm_5m.tif") as d:
        dsm = d.read(1).astype("float64"); dsm[dsm == d.nodata] = np.nan
    with rasterio.open(raw / "dtm_5m.tif") as d:
        dtm = d.read(1).astype("float64"); dtm[dtm == d.nodata] = np.nan
    dtm = np.where(np.isnan(dtm), np.nanmedian(dtm), dtm)
    dsm = np.where(np.isnan(dsm) | (dsm < dtm), dtm, dsm)
    return ((dsm - dtm) < P0.OPEN_MAX) & ~D["body"]


def city_data(key):
    """Visibility classes, zone mask, axis and base layers for one city, in one common shape."""
    if key == "london":
        D = PA.london_layers()
        lev, T, b, axis = D["lev"], D["T"], D["b"], D["axis"]
        g = D["g"]
        zone_polys = g[(g.TYPE == "VC") & g.stpauls]
        base = dict(parks=D["parks"], water=D["water"], roads=D["roads"], rail=D["rail"], boundary=None, pts=D["pts"])
    else:
        D = PA.paris_layers()
        lev, T, b = D["levs"]["sacrecoeur"], D["T"], D["b"]
        axis = D["stats"]["domes"]["sacrecoeur"]["axis_l93"]
        g = D["g"]
        zone_polys = g[g.fuseau == P0.DOMES["sacrecoeur"]["letter"]]
        base = dict(parks=D["green"], water=D["water"], roads=D["roads"], rail=D["rail"], boundary=D["boundary"],
                    pts=P0.panorama_points(g))
    open_ = D["open"]
    if key == "london":                          # the float nDSM, as in sight.viewshed (the stored nDSM is rounded to 0.5 m)
        open_ = london_open_float(D)
    cls = np.where((lev != 255) & open_, P0.CLASS_OF_LEVEL[np.minimum(lev, 6)], 0).astype(np.uint8)
    zone = rasterize([(geom, 1) for geom in zone_polys.geometry], out_shape=lev.shape, transform=T, fill=0).astype(bool)
    # counters on the full 5 m grid, by compass angle (clockwise from north) around the dome axis
    rr, cc = np.nonzero(cls > 0)
    xs, ys = T * (cc + 0.5, rr + 0.5)
    ang = (np.degrees(np.arctan2(xs - axis[0], ys - axis[1])) + 360) % 360
    bins = np.arange(0, 360.5, 0.5)
    km2 = CELL * CELL / 1e6
    seen_cum = np.concatenate([[0], np.cumsum(np.histogram(ang, bins)[0])]) * km2
    zone_cum = np.concatenate([[0], np.cumsum(np.histogram(ang[zone[rr, cc]], bins)[0])]) * km2
    open_km2 = open_.sum() * km2
    # display grid: max class over POOL x POOL blocks
    h, w = (cls.shape[0] // POOL) * POOL, (cls.shape[1] // POOL) * POOL
    disp = cls[:h, :w].reshape(h // POOL, POOL, w // POOL, POOL).max(axis=(1, 3))
    left, top = b.left, b.top
    extent = (left, left + w * CELL, top - h * CELL, top)
    jj, ii = np.meshgrid(np.arange(disp.shape[1]), np.arange(disp.shape[0]))
    cx = left + (jj + 0.5) * CELL * POOL
    cy = top - (ii + 0.5) * CELL * POOL
    disp_ang = (np.degrees(np.arctan2(cx - axis[0], cy - axis[1])) + 360) % 360
    rgba = np.zeros(disp.shape + (4,), dtype="float32")
    for k, c in VIS.items():
        rgba[disp == k] = (*mpl.colors.to_rgb(c), 1.0)
    return dict(key=key, b=b, extent=extent, axis=axis, rgba=rgba, disp_ang=disp_ang, has=disp > 0, bins=bins,
                seen_cum=seen_cum, zone_cum=zone_cum, open_km2=open_km2, zone_polys=zone_polys, base=base)


def base_figure(C, lang):
    """Static layers for one city; returns the figure and the dynamic artists."""
    t = TXT[lang]
    fig = plt.figure(figsize=(W, H), dpi=DPI)
    fig.patch.set_facecolor("#FFFFFF")
    b = C["b"]
    ext_w, ext_h = b.right - b.left, b.top - b.bottom
    mw = 0.92
    mh = mw * W * (ext_h / ext_w) / H
    ax = fig.add_axes([0.04, 0.165, mw, mh])
    ax.set_xlim(b.left, b.right); ax.set_ylim(b.bottom, b.top); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#C8C6C1"); s.set_linewidth(0.5)
    PA.ground(ax, CLEAN["land"])
    B = C["base"]
    if len(B["parks"]):
        B["parks"].plot(ax=ax, color=CLEAN["park"], lw=0, zorder=2)
    B["water"].plot(ax=ax, color=CLEAN["water"], lw=0, zorder=3)
    if B["roads"] is not None and len(B["roads"]):
        B["roads"].plot(ax=ax, color=CLEAN["road"], lw=0.3, zorder=4)
    if B["rail"] is not None and len(B["rail"]):
        B["rail"].plot(ax=ax, color=CLEAN["rail"], lw=0.25, zorder=4.1)
    if B["boundary"] is not None:
        import geopandas as gpd
        gpd.GeoSeries([B["boundary"].boundary], crs=2154).plot(ax=ax, color=CLEAN["boundary"], lw=0.6, linestyle=(0, (3, 2)), zorder=4.2)
    if C["key"] == "london":
        C["zone_polys"].plot(ax=ax, facecolor=mpl.colors.to_rgba(CORR, 0.22), edgecolor=CORR, lw=0.7, zorder=7)
    else:
        mpl.rcParams["hatch.linewidth"] = 0.35
        C["zone_polys"].plot(ax=ax, facecolor="none", edgecolor=FUS, hatch="////", lw=0, zorder=7)
        C["zone_polys"].boundary.plot(ax=ax, color=FUS, lw=0.6, zorder=7.01)
    ax.scatter(B["pts"].geometry.x, B["pts"].geometry.y, s=10, facecolor=P["text"], edgecolor="white", lw=0.5, zorder=9)
    ax.scatter([C["axis"][0]], [C["axis"][1]], s=40, facecolor=P["accent"], edgecolor=P["text"], lw=0.6, zorder=10)
    PA.halo_under(ax.annotate(t["dome"][C["key"]], C["axis"], (C["axis"][0] + 700, C["axis"][1] + 900), ha="left", va="center",
                              color=P["text"], zorder=12, fontproperties=S.font("label_bold", lang, 7.5),
                              arrowprops=dict(arrowstyle="-", color=P["text"], lw=0.5, shrinkA=0, shrinkB=4)), ("#FFFFFF", 2.0))
    sx, sy = b.right - 700 - 5000, b.bottom + 600
    ax.plot([sx, sx + 5000], [sy, sy], color=P["text"], lw=1.0, solid_capstyle="butt", zorder=12)
    ax.text(sx + 2500, sy + 180, "5 km" if lang == "en" else "5 км", ha="center", va="bottom",
            fontproperties=S.font("label", lang, 6), color=P["text"], zorder=12)
    # dynamic artists
    img = ax.imshow(np.zeros_like(C["rgba"]), extent=C["extent"], interpolation="antialiased", zorder=6)
    trail = [Wedge(C["axis"], 40000, 0, 1, facecolor=NAVY, edgecolor="none", alpha=a, zorder=6.5) for a in (0.10, 0.07, 0.045, 0.025, 0.012)]
    for w_ in trail:
        ax.add_patch(w_)
    head, = ax.plot([], [], color=NAVY, lw=0.7, alpha=0.45, zorder=6.6)
    # text block
    fig.text(0.04, 0.975, t["title"], fontproperties=S.font("title", lang, 13), color=NAVY, va="top", ha="left")
    fig.text(0.04, 0.935, t["city"][C["key"]], fontproperties=S.font("label_bold", lang, 9), color=P["text"], va="top", ha="left")
    n_seen = fig.text(0.04, 0.895, "", fontproperties=S.font("title", lang, 18), color=VIS[3], va="top", ha="left")
    l_seen = fig.text(0.04, 0.852, t["seen"], fontproperties=S.font("label", lang, 7), color=P["muted"], va="top", ha="left")
    n_in = fig.text(0.55, 0.895, "", fontproperties=S.font("title", lang, 18), color=CORR if C["key"] == "london" else FUS, va="top", ha="left")
    l_in = fig.text(0.55, 0.852, t["inside"][C["key"]], fontproperties=S.font("label", lang, 7), color=P["muted"], va="top", ha="left")
    # legend and footer
    x = 0.04
    for k, lab in zip((3, 2, 1), t["leg"]):
        fig.patches.append(Rectangle((x, 0.118), 0.03, 0.013, transform=fig.transFigure, facecolor=VIS[k], edgecolor=VIS[k]))
        tx = fig.text(x + 0.037, 0.1245, lab, fontproperties=S.font("legend", lang, 6.5), color=P["text"], va="center")
        fig.canvas.draw()
        x = tx.get_window_extent(renderer=fig.canvas.get_renderer()).x1 / fig.bbox.width + 0.03
    if C["key"] == "london":
        fig.patches.append(Rectangle((0.04, 0.093), 0.03, 0.013, transform=fig.transFigure, facecolor=mpl.colors.to_rgba(CORR, 0.22), edgecolor=CORR, lw=0.8))
    else:
        fig.patches.append(Rectangle((0.04, 0.093), 0.03, 0.013, transform=fig.transFigure, facecolor="none", edgecolor=FUS, hatch="////", lw=0.6))
    fig.text(0.077, 0.0995, t["zone"][C["key"]], fontproperties=S.font("legend", lang, 6.5), color=P["text"], va="center")
    fig.text(0.04, 0.03, t["src"], fontproperties=S.font("body", lang, 5), color=P["muted"], va="bottom", ha="left", linespacing=1.4)
    fig.text(0.04, 0.012, t["sign"], fontproperties=S.font("body", lang, 5), color=P["muted"], va="bottom", ha="left")
    return fig, ax, dict(img=img, trail=trail, head=head, n_seen=n_seen, n_in=n_in, l_seen=l_seen, l_in=l_in)


def ease(u):
    return u * u * (3 - 2 * u)


def frames_for_city(C, lang, writer):
    t = TXT[lang]
    fig, ax, A = base_figure(C, lang)
    dyn = [A["img"], *A["trail"], A["head"]]
    for a in dyn:
        a.set_visible(False)
    A["n_seen"].set_visible(False); A["n_in"].set_visible(False)
    fig.canvas.draw()
    bg = fig.canvas.copy_from_bbox(fig.bbox)
    for a in dyn:
        a.set_visible(True)
    A["n_seen"].set_visible(True); A["n_in"].set_visible(True)
    seq = [0.0] * int(0.8 * FPS) + [ease(i / (6 * FPS - 1)) * 360 for i in range(6 * FPS)] + [360.0] * int(1.8 * FPS)
    ax0, ay0 = C["axis"]
    for n, theta in enumerate(seq):
        fig.canvas.restore_region(bg)
        rgba = C["rgba"].copy()
        rgba[(C["disp_ang"] > theta) | ~C["has"]] = 0
        A["img"].set_data(rgba)
        sweeping = 0 < theta < 360
        for i, w_ in enumerate(A["trail"]):
            w_.set_visible(sweeping)
            w_.set_theta1(90 - theta + i * 4); w_.set_theta2(90 - theta + (i + 1) * 4)
        r = 40000
        A["head"].set_visible(sweeping)
        A["head"].set_data([ax0, ax0 + r * np.sin(np.radians(theta))], [ay0, ay0 + r * np.cos(np.radians(theta))])
        k = int(round(theta / 0.5))
        seen, zone = C["seen_cum"][k], C["zone_cum"][k]
        A["n_seen"].set_text(f"{fmt(seen, lang, 2)} {t['km']} · {fmt(100 * seen / C['open_km2'], lang, 1)}%")
        A["n_in"].set_text(f"{fmt(100 * zone / seen, lang, 0) if seen > 0 else '0'}%")
        for a in (A["img"], *A["trail"], A["head"]):
            ax.draw_artist(a)
        fig.draw_artist(A["n_seen"]); fig.draw_artist(A["n_in"])
        writer.append_data(np.asarray(fig.canvas.buffer_rgba())[..., :3].copy())
    final = dict(share=100 * C["seen_cum"][-1] / C["open_km2"], seen=C["seen_cum"][-1],
                 outside=100 * (1 - C["zone_cum"][-1] / C["seen_cum"][-1]))
    plt.close(fig)
    return final


def end_card(res, lang, writer):
    t = TXT[lang]
    fig = plt.figure(figsize=(W, H), dpi=DPI)
    fig.patch.set_facecolor("#FFFFFF")
    fig.text(0.06, 0.86, t["end_title"], fontproperties=S.font("title", lang, 15), color=NAVY, va="top")
    for i, (key, col) in enumerate((("london", CORR), ("paris", FUS))):
        x = 0.06 + i * 0.47
        fig.text(x, 0.74, t["city"][key].split(" · ")[0], fontproperties=S.font("label_bold", lang, 11), color=P["text"], va="top")
        fig.text(x, 0.69, t["dome"][key], fontproperties=S.font("label", lang, 8), color=P["muted"], va="top")
        fig.text(x, 0.62, f"{fmt(res[key]['share'], lang, 1)}%", fontproperties=S.font("title", lang, 30), color=VIS[3], va="top")
        fig.text(x, 0.53, t["end_line"], fontproperties=S.font("label", lang, 7), color=P["muted"], va="top", wrap=True)
        fig.text(x, 0.45, f"{fmt(res[key]['outside'], lang, 0)}%", fontproperties=S.font("title", lang, 30), color=col, va="top")
        fig.text(x, 0.36, t["end_out"], fontproperties=S.font("label", lang, 7), color=P["muted"], va="top")
    fig.text(0.06, 0.26, t["end_note"], fontproperties=S.font("label_bold", lang, 8), color=P["text"], va="top", wrap=True)
    fig.text(0.06, 0.012, t["sign"], fontproperties=S.font("body", lang, 5.5), color=P["muted"], va="bottom")
    fig.canvas.draw()
    frame = np.asarray(fig.canvas.buffer_rgba())[..., :3].copy()
    for _ in range(int(3.5 * FPS)):
        writer.append_data(frame)
    plt.close(fig)


def main(lang):
    S.apply()
    out = HERE / "video" / f"sweep_{lang}.mp4"
    out.parent.mkdir(exist_ok=True)
    writer = imageio.get_writer(out, fps=FPS, codec="libx264", quality=None, macro_block_size=2, ffmpeg_params=["-crf", "20", "-movflags", "+faststart"])
    res = {}
    for key in ("london", "paris"):
        res[key] = frames_for_city(city_data(key), lang, writer)
        print(key, {k: round(v, 3) for k, v in res[key].items()}, flush=True)
    end_card(res, lang, writer)
    writer.close()
    print(out)


if __name__ == "__main__":
    for lang in (sys.argv[1:] or ["en", "ru"]):
        main(lang)
