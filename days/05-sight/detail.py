"""Day 5, second frame: the 5 m detail behind the 50 m overview, and three real lines of sight in London.

Top: two zoom windows at the model's own 5 m resolution (London: St Paul's and the river bend; Paris: the Sacré-Cœur
and the La Chapelle rail yards), open ground coloured by the lowest part of the dome it sees, open ground that sees
nothing in light grey, buildings and trees left blank. Bottom: a locator and three sections along the line of sight,
drawn from the same 5 m LiDAR surfaces and the same ray rule as the map (eye 1.6 m above ground, earth curvature and
refraction k = 0.13, the cathedral's body removed from the obstacles):
  A  Parliament Hill summit, the protected LVMF viewpoint            B  St Pancras Way, under the same corridor
  C  Waterloo Bridge, no LVMF corridor (St Paul's Heights instead)

    python detail.py en ru           # map_en_detail.png, map_ru_detail.png
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "paris"))
import paris_apur as PA            # noqa: E402  (fonts, colours, Paris layers, halo helper)
import public_space as PS          # noqa: E402  (exact London open ground, zoom windows)
import geopandas as gpd            # noqa: E402
import matplotlib as mpl           # noqa: E402
import matplotlib.pyplot as plt    # noqa: E402
import numpy as np                 # noqa: E402
import rasterio                    # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from rasterio.features import rasterize  # noqa: E402
from shapely.geometry import Point  # noqa: E402

S, P0, L0, CLEAN, VIS, P = PA.S, PA.P0, PA.L0, PA.CLEAN, PA.VIS, PA.P
CORR, FUS, NAVY = PA.CORR, PA.FUS, P["accent3"]
LAW, LAW_DASH, CITY = PA.LAW, PA.LAW_DASH, PA.CITY      # the law as a thin grey dash, as on the main frame
FS, X0 = PA.FS, PA.X0                                  # the type scale and left edge of the main frame
NOVIEW, OBJ, GROUND, BLOCK = "#E1E1DE", "#C7C8C4", "#E6E6E3", "#B4472E"      # neutral greys (anti-AI audit: no sand beige)
BODY = "#8B8C88"
SECTIONS = {"A": (527665, 186131), "B": (529402.5, 184137.5), "C": (530677.5, 180692.5)}   # BNG; B: St Pancras Way, inside VC 2A.1; C: Waterloo Bridge deck
# every viewer is snapped to the centre of its 5 m cell, so the section reproduces the map's value for that cell exactly
SHOW = [0, 2, 4]          # target levels drawn in the sections: 111 m (cross), 85 m (Golden Gallery), 53 m (base of the dome)
TXT = {
    "en": dict(
        title="From Waterloo Bridge the whole dome is visible; from the street under the protected line, nothing",
        sub="The model's own 5 m cells. Top: the two zoom windows framed on the overview. Bottom: three real lines of sight in London, "
            "cut through the LiDAR surface.",
        leg=["whole dome", "upper dome", "lantern only", "open ground, dome not visible"], law="protected view zone (LVMF corridor, faisceau de vues)",
        zoom={"london": "London · St Paul's and the river", "paris": "Paris · Sacré-Cœur and La Chapelle"},
        zcap={"london": "In this window {any}% of the open ground sees some part of the dome, {whole}% the whole dome.",
              "paris": "In this window {any}% of the open ground sees some part of the dome, {whole}% the whole dome; the long open\n"
                       "strips are the railway lands north of Gare du Nord and Gare de l'Est."},
        city="Paris city limit", thames="River Thames", stp="St Paul's", sc="Sacré-Cœur",
        sec={"A": "A · Parliament Hill summit, the protected viewpoint", "B": "B · St Pancras Way, under the same corridor",
             "C": "C · Waterloo Bridge, no LVMF corridor"},
        verdict={3: "sees the whole dome", 2: "sees the upper dome", 1: "sees only the lantern and cross", 0: "sees nothing of the dome"},
        blocked="first obstacle for the cross: {h:.0f} m tall, {d:.0f} m away", dist="{d:.1f} km to the dome", xlab="distance from the viewer, km",
        corridor="in this corridor 3–5 km out, {n} street cells of {c:,} see the dome",
        corridor0="none of this corridor's {c:,} street cells 3–5 km out sees the dome",
        ylab="m above sea level", vex="vertical ×{v:.0f}", lines=["to the cross, 111 m", "to the Golden Gallery, 85 m", "to the base of the dome, 53 m",
                                                                   "blocked line", "first obstacle", "terrain", "buildings and trees", "the cathedral"],
        tgt=["cross 111 m", "Golden Gallery 85 m", "base of the dome 53 m"], locator="Lines of sight",
        src=("Data: Environment Agency LiDAR composite DSM/DTM (OGL v3), GLA LVMF (OGL v2); IGN LiDAR HD (Licence Ouverte 2.0), Ville de Paris PLU (ODbL); "
             "OpenStreetMap, Overture Maps (ODbL).\nSections: the 5 m surfaces sampled every 2.5 m along the line; same ray rule as the map (eye 1.6 m, "
             "k = 0.13, cathedral body removed).")),
    "ru": dict(
        title="С моста Ватерлоо виден весь купол, с улицы под охраняемым лучом не видно ничего",
        sub="Ячейки модели, 5 м. Сверху: два окна, отмеченные на обзорной карте. Снизу: три настоящих луча зрения в Лондоне, "
            "разрезанные через поверхность LiDAR.",
        leg=["весь купол", "верх купола", "только фонарь", "открытая земля, купол не виден"], law="охраняемая зона вида (коридор LVMF, пучок видов)",
        zoom={"london": "Лондон · собор св. Павла и река", "paris": "Париж · Сакре-Кёр и Ла-Шапель"},
        zcap={"london": "В этом окне {any}% открытой земли видят хоть часть купола, {whole}% видят весь купол.",
              "paris": "В этом окне {any}% открытой земли видят хоть часть купола, {whole}% видят весь купол; длинные открытые\n"
                       "полосы: железнодорожные земли к северу от Северного и Восточного вокзалов."},
        city="граница Парижа", thames="Темза", stp="Собор св. Павла", sc="Сакре-Кёр",
        sec={"A": "A · вершина Парламент-хилл, охраняемая точка", "B": "B · St Pancras Way, под тем же коридором",
             "C": "C · мост Ватерлоо, коридора LVMF нет"},
        verdict={3: "виден весь купол", 2: "виден верх купола", 1: "видны только фонарь и крест", 0: "купол не виден"},
        blocked="первое препятствие для креста: высота {h:.0f} м, в {d:.0f} м", dist="{d:.1f} км до купола", xlab="расстояние от наблюдателя, км",
        corridor="в этом коридоре в 3–5 км купол видят {n} из {c:,} ячеек улиц",
        corridor0="ни одна из {c:,} ячеек улиц этого коридора в 3–5 км не видит купол",
        ylab="м над уровнем моря", vex="вертикаль ×{v:.0f}", lines=["к кресту, 111 м", "к Золотой галерее, 85 м", "к основанию купола, 53 м",
                                                                  "закрытый луч", "первое препятствие", "рельеф", "здания и деревья", "собор"],
        tgt=["крест 111 м", "Золотая галерея 85 м", "основание купола 53 м"], locator="Лучи зрения",
        src=("Данные: Environment Agency, LiDAR DSM/DTM (OGL v3), GLA LVMF (OGL v2); IGN LiDAR HD (Licence Ouverte 2.0), Ville de Paris PLU (ODbL); "
             "OpenStreetMap, Overture Maps (ODbL).\nРазрезы: поверхности 5 м с шагом 2,5 м вдоль луча; правило то же, что на карте (глаз 1,6 м, "
             "k = 0,13, корпус собора убран).")),
}


def london():
    open_ground, T, dsm, dtm, body = PS.london_open()
    with rasterio.open(L0.DER / "visible_level.tif") as d:
        lev = d.read(1)
    st = json.loads((L0.DER / "stats.json").read_text())
    water = L0.water()
    wm = rasterize([(g, 1) for g in water.geometry], out_shape=lev.shape, transform=T, fill=0).astype(bool)
    g = L0.lvmf()
    return dict(lev=lev, open=open_ground, T=T, dsm=dsm, dtm=dtm, body=body, obs=np.where(body, dtm, dsm), water=water, wm=wm,
                g=g, axis=st["dome_axis_bng"], hg=st["ground_m_aod"], levels=np.array(st["levels_m_above_ground"]))


def class_image(lev, open_ground, wm):
    cls = np.where((lev != 255) & open_ground, L0.CLASS_OF_LEVEL[np.minimum(lev, 6)], 0)
    rgba = np.zeros(lev.shape + (4,), dtype="float32")
    rgba[open_ground & ~wm & (cls == 0)] = (*mpl.colors.to_rgb(NOVIEW), 1.0)
    for k, c in VIS.items():
        rgba[cls == k] = (*mpl.colors.to_rgb(c), 1.0)
    return rgba


def window(ax, key):
    x0, y0, x1, y1 = PS.ZOOMS[key]
    ax.set_xlim(x0, x1); ax.set_ylim(y0, y1); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color(P["text"]); s.set_linewidth(0.6)
    PA.ground(ax, CLEAN["land"])
    return x0, y0, x1, y1


def window_stats(lev, open_ground, T, box, outside=None):
    x0, y0, x1, y1 = box
    c0, r1 = ~T * (x0, y0); c1, r0 = ~T * (x1, y1)
    sl = (slice(int(r0), int(r1)), slice(int(c0), int(c1)))
    og, lv = open_ground[sl], lev[sl]
    sees = og & (lv != 255)
    whole = og & (lv != 255) & (L0.CLASS_OF_LEVEL[np.minimum(lv, 6)] == 3)
    out = dict(any=100 * sees.sum() / og.sum(), whole=100 * whole.sum() / og.sum())
    if outside is not None:
        out["out"] = 100 * (sees & outside[sl]).sum() / max(sees.sum(), 1)
    return out


def section(Ld, xy):
    """Profile along the line from the viewer at xy to the dome axis, with the map's ray rule. Returns arrays and,
    for every target level, (visible, index of the first obstacle)."""
    T, (ax, ay) = Ld["T"], Ld["axis"]
    c, r = ~T * xy
    x, y = T * (int(c) + 0.5, int(r) + 0.5)               # centre of the viewer's cell
    D = float(np.hypot(x - ax, y - ay))
    n = int(D / 2.5) + 1
    s = np.linspace(0, D, n)                                # distance from the viewer
    xs, ys = x + (ax - x) * s / D, y + (ay - y) * s / D
    cols = ((xs - T.c) / T.a).astype(int); rows = ((ys - T.f) / T.e).astype(int)
    dsm, dtm, obs = Ld["dsm"][rows, cols], Ld["dtm"][rows, cols], Ld["obs"][rows, cols]
    rt = D - s                                              # distance from the dome
    drop = (1 - L0.K_REFR) * rt ** 2 / (2 * L0.R_EARTH)
    eye = dtm[0] + L0.EYE
    eye_c = eye - drop[0]
    res = []
    for ht in Ld["levels"]:
        tgt = Ld["hg"] + ht
        line_c = eye_c + (tgt - eye_c) * s / D               # straight in the curvature-corrected frame
        inner = (s > 3.5) & (rt > 2.5)
        hit = np.nonzero(inner & (obs - drop > line_c))[0]
        res.append((hit.size == 0, int(hit[0]) if hit.size else None, line_c + drop))
    return dict(s=s, dsm=dsm, dtm=dtm, D=D, eye=eye, res=res, ndsm=dsm - dtm, body=Ld["body"][rows, cols])


def lowest_class(res):
    seen = [i for i, (vis, _, _) in enumerate(res) if vis]
    return 0 if not seen else int(L0.CLASS_OF_LEVEL[max(seen)])


def draw_section(ax, sec, t, lang):
    s, km = sec["s"], sec["s"] / 1000
    ax.fill_between(km, 0, sec["dtm"], color=GROUND, lw=0, zorder=1)
    ax.fill_between(km, sec["dtm"], sec["dsm"], where=sec["dsm"] - sec["dtm"] > 0.5, color=OBJ, lw=0, zorder=2, step="mid")
    ax.fill_between(km, sec["dtm"], sec["dsm"], where=sec["body"], color=BODY, lw=0, zorder=2.1, step="mid")
    cols = {0: VIS[1], 2: VIS[2], 4: VIS[3]}
    for i in SHOW:
        vis, hit, line = sec["res"][i]
        end = len(s) if vis else hit + 1
        ax.plot(km[:end], line[:end], color=cols[i] if vis else "#9A958C", lw=0.9 if vis else 0.7, zorder=4,
                linestyle="-" if vis else (0, (3, 2)))
        if not vis:
            ax.plot(km[hit:], line[hit:], color="#9A958C", lw=0.5, linestyle=(0, (1, 2)), zorder=3.9, alpha=0.7)
            ax.scatter([km[hit]], [line[hit]], marker="x", s=14, color=BLOCK, lw=1.0, zorder=5)
    ax.scatter([0], [sec["eye"]], s=10, color=P["text"], zorder=6)
    ax.set_xlim(-0.02 * km[-1], km[-1] * 1.02)
    ax.set_ylim(0, 140)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#9A958C"); ax.spines[sp].set_linewidth(0.5)
    ax.tick_params(labelsize=4.8, length=2, width=0.4, colors=P["muted"])
    for lab in ax.get_xticklabels() + ax.get_yticklabels():
        lab.set_fontproperties(S.font("label", lang, FS["tiny"]))
    # vertical exaggeration from the axes' physical size
    bb = ax.get_position()
    fig = ax.figure
    m_per_in_x = (km[-1] * 1.04 * 1000) / (bb.width * fig.get_figwidth())
    m_per_in_y = 140 / (bb.height * fig.get_figheight())
    ax.text(0.99, 0.97, t["vex"].format(v=m_per_in_x / m_per_in_y), transform=ax.transAxes, ha="right", va="top",
            fontproperties=S.font("label", lang, FS["tiny"]), color=P["muted"])


def figure(lang, Ld, DP):
    t = TXT[lang]
    S.apply()
    W, H = 10.8, 6.75
    fig = plt.figure(figsize=(W, H), facecolor=PA.PAGE)
    fig.text(X0, 0.975, PA.title_case(t["title"]), fontproperties=S.font("title", lang, FS["title"]), color=NAVY, va="top")
    fig.text(X0, 0.932, t["sub"], fontproperties=S.font("subtitle", lang, FS["body"]), color=P["muted"], va="top")
    # legend row (top right)
    x = X0
    yl = 0.902
    items = [(VIS[3], t["leg"][0]), (VIS[2], t["leg"][1]), (VIS[1], t["leg"][2]), (NOVIEW, t["leg"][3])]
    for col, lab in items:
        fig.patches.append(Rectangle((x, yl - 0.006), 0.022, 0.011, transform=fig.transFigure, facecolor=col, edgecolor=col))
        tx = fig.text(x + 0.027, yl, lab, fontproperties=S.font("legend", lang, FS["small"]), color=P["text"], va="center")
        fig.canvas.draw()
        x = tx.get_window_extent(renderer=fig.canvas.get_renderer()).x1 / fig.bbox.width + 0.018
    for col, ls, lab in ((LAW, LAW_DASH, t["law"]), (CITY, "-", t["city"])):
        fig.add_artist(Line2D([x, x + 0.022], [yl, yl], transform=fig.transFigure, color=col, lw=0.8, linestyle=ls))
        tx = fig.text(x + 0.027, yl, lab, fontproperties=S.font("legend", lang, FS["small"]), color=P["text"], va="center")
        fig.canvas.draw()
        x = tx.get_window_extent(renderer=fig.canvas.get_renderer()).x1 / fig.bbox.width + 0.018

    # ---- zoom windows
    boxes = {"london": [X0, 0.445, 0.445, 0.40], "paris": [0.525, 0.445, 0.45, 0.40]}
    paris_city = rasterize([(DP["boundary"], 1)], out_shape=DP["levs"]["sacrecoeur"].shape, transform=DP["T"], fill=0).astype(bool)
    halo = ("#FFFFFF", 1.8)
    for key, bx in boxes.items():
        ax = fig.add_axes(bx)
        x0, y0, x1, y1 = window(ax, key)
        if key == "london":
            Ld["water"].plot(ax=ax, color=CLEAN["water"], lw=0, zorder=2)
            b = rasterio.transform.array_bounds(*Ld["lev"].shape, Ld["T"])
            ax.imshow(class_image(Ld["lev"], Ld["open"], Ld["wm"]), extent=(b[0], b[2], b[1], b[3]), interpolation="nearest", zorder=3)
            sp = Ld["g"][(Ld["g"].TYPE == "VC") & Ld["g"].stpauls]
            sp.boundary.plot(ax=ax, color=LAW, lw=0.6, linestyle=LAW_DASH, zorder=6)
            axx, axy = Ld["axis"]
            cx, cy = SECTIONS["C"]
            ax.plot([cx, axx], [cy, axy], color=P["text"], lw=0.5, linestyle=(0, (2, 1.5)), zorder=7)
            ax.scatter([cx], [cy], s=14, color=P["text"], zorder=8)
            PA.halo_under(ax.text(cx - 60, cy - 90, "C", ha="right", va="top", fontproperties=S.font("label_bold", lang, FS["body"]), color=P["text"], zorder=9), halo)
            ax.scatter([axx], [axy], s=34, facecolor=P["accent"], edgecolor=P["text"], lw=0.6, zorder=8)
            PA.halo_under(ax.annotate(t["stp"], (axx, axy), (axx + 260, axy + 420), ha="left", va="center", fontproperties=S.font("label_bold", lang, FS["body"]),
                                      color=P["text"], zorder=9, arrowprops=dict(arrowstyle="-", color=P["text"], lw=0.5, shrinkA=0, shrinkB=4)), halo)
            PA.halo_under(ax.text(530350, 180240, t["thames"], ha="left", va="center", rotation=-8, fontproperties=S.font("water", lang, FS["small"]),
                                  color="#447FB3", zorder=9), halo)
            ws = window_stats(Ld["lev"], Ld["open"], Ld["T"], PS.ZOOMS[key])
            cap = t["zcap"][key].format(any=L0.fmt(ws["any"], lang), whole=L0.fmt(ws["whole"], lang))
        else:
            DP["water"].plot(ax=ax, color=CLEAN["water"], lw=0, zorder=2)
            b = rasterio.transform.array_bounds(*DP["levs"]["sacrecoeur"].shape, DP["T"])
            ax.imshow(class_image(DP["levs"]["sacrecoeur"], DP["open"], DP["water_mask"]), extent=(b[0], b[2], b[1], b[3]),
                      interpolation="nearest", zorder=3)
            own = DP["g"][DP["g"].fuseau == P0.DOMES["sacrecoeur"]["letter"]].dissolve()
            own.boundary.plot(ax=ax, color=LAW, lw=0.6, linestyle=LAW_DASH, zorder=6)
            gpd.GeoSeries([DP["boundary"].boundary], crs=2154).plot(ax=ax, color=CITY, lw=0.7, zorder=6.5)
            axx, axy = DP["stats"]["domes"]["sacrecoeur"]["axis_l93"]
            ax.scatter([axx], [axy], s=34, facecolor=P["accent"], edgecolor=P["text"], lw=0.6, zorder=8)
            PA.halo_under(ax.annotate(t["sc"], (axx, axy), (axx - 300, axy - 330), ha="right", va="center", fontproperties=S.font("label_bold", lang, FS["body"]),
                                      color=P["text"], zorder=9, arrowprops=dict(arrowstyle="-", color=P["text"], lw=0.5, shrinkA=0, shrinkB=4)), halo)
            ws = window_stats(DP["levs"]["sacrecoeur"], DP["open"], DP["T"], PS.ZOOMS[key])
            cap = t["zcap"][key].format(any=L0.fmt(ws["any"], lang), whole=L0.fmt(ws["whole"], lang))
        # 500 m scale bar
        sx, sy = x1 - 160 - 500, y0 + 140
        ax.plot([sx, sx + 500], [sy, sy], color=P["text"], lw=0.9, solid_capstyle="butt", zorder=10)
        PA.halo_under(ax.text(sx + 250, sy + 50, "500 m" if lang == "en" else "500 м", ha="center", va="bottom",
                              fontproperties=S.font("label", lang, FS["small"]), color=P["text"], zorder=10), halo)
        fig.text(bx[0], bx[1] + bx[3] + 0.007, t["zoom"][key], fontproperties=S.font("label_bold", lang, FS["head"]), color=NAVY, va="bottom")
        fig.text(bx[0], bx[1] - 0.008, cap, fontproperties=S.font("label", lang, FS["body"]), color=P["text"], va="top", linespacing=1.35)

    # ---- locator: the London extent with the three lines
    lb = Ld["T"]
    loc = fig.add_axes([X0, 0.14, 0.14, 0.235])
    b = rasterio.transform.array_bounds(*Ld["lev"].shape, lb)
    loc.set_xlim(b[0], b[2]); loc.set_ylim(b[1], b[3]); loc.set_aspect("equal"); loc.set_xticks([]); loc.set_yticks([])
    for s_ in loc.spines.values():
        s_.set_color("#C8C6C1"); s_.set_linewidth(0.5)
    PA.ground(loc, CLEAN["land"])
    Ld["water"].plot(ax=loc, color=CLEAN["water"], lw=0, zorder=2)
    sp = Ld["g"][(Ld["g"].TYPE == "VC") & Ld["g"].stpauls]
    sp.boundary.plot(ax=loc, color=LAW, lw=0.4, linestyle=LAW_DASH, zorder=3)
    axx, axy = Ld["axis"]
    for k, (sx_, sy_) in SECTIONS.items():
        loc.plot([sx_, axx], [sy_, axy], color=P["text"], lw=0.6, zorder=4)
        loc.scatter([sx_], [sy_], s=8, color=P["text"], zorder=5)
        off = {"A": (-250, 250, "right"), "B": (250, -150, "left"), "C": (-250, -250, "right")}[k]
        PA.halo_under(loc.text(sx_ + off[0], sy_ + off[1], k, ha=off[2], va="center", fontproperties=S.font("label_bold", lang, 6.4),
                               color=P["text"], zorder=6), halo)
    loc.scatter([axx], [axy], s=16, facecolor=P["accent"], edgecolor=P["text"], lw=0.5, zorder=6)
    zx0, zy0, zx1, zy1 = PS.ZOOMS["london"]
    loc.add_patch(Rectangle((zx0, zy0), zx1 - zx0, zy1 - zy0, facecolor="none", edgecolor=P["text"], lw=0.4, zorder=5))
    fig.text(X0, 0.385, t["locator"], fontproperties=S.font("label_bold", lang, FS["body"]), color=NAVY, va="bottom")

    # ---- sections
    xs = {"A": 0.215, "B": 0.475, "C": 0.735}
    for k, xy in SECTIONS.items():
        sec = section(Ld, xy)
        lc = lowest_class(sec["res"])
        c_, r_ = ~Ld["T"] * xy
        raster_lc = 0 if Ld["lev"][int(r_), int(c_)] == 255 else int(L0.CLASS_OF_LEVEL[min(int(Ld["lev"][int(r_), int(c_)]), 6)])
        print(k, "section class", lc, "raster class at the cell", raster_lc, f"D={sec['D']:.0f} m")
        ax = fig.add_axes([xs[k], 0.145, 0.235, 0.17])
        draw_section(ax, sec, t, lang)
        verdict = t["verdict"][lc]
        fig.text(xs[k], 0.385, t["sec"][k], fontproperties=S.font("label_bold", lang, 6.4), color=NAVY, va="bottom")
        fig.text(xs[k], 0.378, t["dist"].format(d=sec["D"] / 1000).replace(".", "," if lang == "ru" else ".") + " · " + verdict,
                 fontproperties=S.font("label", lang, FS["small"]), color=VIS[3] if lc else BLOCK, va="top")
        if not sec["res"][0][0]:
            hit = sec["res"][0][1]
            fig.text(xs[k], 0.358, t["blocked"].format(h=sec["ndsm"][hit], d=sec["s"][hit]), fontproperties=S.font("label", lang, FS["small"]),
                     color=P["muted"], va="top")
        if k == "B":
            cor = json.loads((L0.DER / "stats.json").read_text())["public_space"]["corridors"]["2A.1"]
            line = (t["corridor0"] if cor["seeing_3_5km"] == 0 else t["corridor"]).format(n=cor["seeing_3_5km"], c=cor["public_cells_3_5km"])
            fig.text(xs[k], 0.341, line.replace(",", " ") if lang == "ru" else line, fontproperties=S.font("label", lang, FS["small"]), color=P["muted"], va="top")
        if k == "A":
            ax.set_ylabel(t["ylab"], fontproperties=S.font("label", lang, FS["tiny"]), color=P["muted"])
        ax.set_xlabel(t["xlab"], fontproperties=S.font("label", lang, FS["tiny"]), color=P["muted"], labelpad=1.5)
    # section legend
    x = 0.215
    yl = 0.08
    entries = [("line", VIS[1], "-", t["lines"][0]), ("line", VIS[2], "-", t["lines"][1]), ("line", VIS[3], "-", t["lines"][2]),
               ("line", "#9A958C", (0, (3, 2)), t["lines"][3]), ("x", BLOCK, None, t["lines"][4]),
               ("box", GROUND, None, t["lines"][5]), ("box", OBJ, None, t["lines"][6]), ("box", BODY, None, t["lines"][7])]
    for kind, col, ls, lab in entries:
        if kind == "line":
            fig.add_artist(Line2D([x, x + 0.02], [yl, yl], transform=fig.transFigure, color=col, lw=1.0, linestyle=ls))
        elif kind == "x":
            fig.add_artist(Line2D([x + 0.01], [yl], transform=fig.transFigure, color=col, marker="x", markersize=3.5, lw=0))
        else:
            fig.patches.append(Rectangle((x, yl - 0.0055), 0.02, 0.011, transform=fig.transFigure, facecolor=col, edgecolor=col))
        tx = fig.text(x + 0.025, yl, lab, fontproperties=S.font("legend", lang, FS["small"]), color=P["text"], va="center")
        fig.canvas.draw()
        x = tx.get_window_extent(renderer=fig.canvas.get_renderer()).x1 / fig.bbox.width + 0.013
    fig.text(X0, 0.03, t["src"], fontproperties=S.font("body", lang, FS["tiny"]), color=P["muted"], va="bottom", linespacing=1.4)
    PA.signature(fig, 5, style=S.STYLE)
    out = HERE / f"map_{lang}_detail.png"
    fig.savefig(out, dpi=300, facecolor=PA.PAGE)
    plt.close(fig)
    print(out)


if __name__ == "__main__":
    Ld = london()
    DP = PA.paris_layers()
    for lang in (sys.argv[1:] or ["en", "ru"]):
        figure(lang, Ld, DP)
