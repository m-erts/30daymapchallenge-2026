"""Day 5 in the London manner, the main map: the visibility result on an Ordnance Survey-style sheet (shared/styles/ldn_os
with the OS Open Zoomstack Light base recommended for data, the OS GeoDataViz sequential scale for the dome, one accent for
the LVMF corridors, Source Sans 3, National Grid). The dark DESIGN.md version stays as map_*_old.png (sight.py).

    python fetch_os_layers.py        # parks, major roads, rail from Overture -> data/raw/os_layers.gpkg
    python sight_os.py en ru         # map_en_london.png, map_ru_london.png (the London panel on its own)
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1] / "shared"))
import geopandas as gpd, matplotlib as mpl, matplotlib.patheffects as pe, matplotlib.pyplot as plt, numpy as np, rasterio
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from rasterio.features import rasterize
import sight as S0
from styles import ldn_os as S
from styles.common import grid_lines, km_ticks, scalebar_fig, ground

P = dict(S.PALETTE, **dict(bg="#F1EFEC", paper="#F1EFEC", land="#F1EFEC", water="#C5CDD0", water_shadow="#C5CDD0",
                           building="#E1E0DB", park="#E6EAE2", park_edge="#DCE2D6", road="#FFFFFF", road_casing="#DCDAD5",
                           road_primary="#FFFFFF", rail="#C9C7C2", grid="#D3D9DC", muted="#6A6F73", halo="#F1EFEC"))   # OS Zoomstack Light
_gdv = mpl.colors.LinearSegmentedColormap.from_list("gdv", S.GDV["sequential_s1"])
import public_space as PS
CLS = {k: mpl.colors.to_hex(PS.class_share_colours()[(k, len(PS.SAT) - 1)]) for k in (1, 2, 3)}   # lantern only -> whole dome:
# the scale shared with the Paris panel, the comparison and the detail frame
# Clean base (Masha, 04.11.2026): the per-cell LiDAR buildings and trees read as a dirty grey mass at this scale, so they are used
# for the lines of sight but not drawn; quiet land, pale water, light parks, thin roads.
P.update(land="#F7F6F3", bg="#F7F6F3", paper="#F7F6F3", halo="#F7F6F3", water="#D3E4EC", park="#E2EBDA", park_edge="#E2EBDA",
         road="#DCD8D0", road_casing="#DCD8D0", road_primary="#D2CDC4", rail="#D3CFC7")
CORR = "#F28522"                                          # the legal layer: one OS GeoDataViz accent (orange)
OTHER = "#A9A6A0"
LAYERS = HERE / "data" / "raw" / "os_layers.gpkg"
EXTRA = {"en": ("Quiet base after OS Open Zoomstack Light (Ordnance Survey, OGL v3); LiDAR buildings and trees are used for the lines of sight\nbut not drawn. Parks, roads, rail: Overture Maps (ODbL).",
                "parks", "corridors to Westminster and the Tower", "5 km   ·   grid lines 1 km, British National Grid",
                "Orange: the eight view corridors that the London View Management Framework protects\n"
                "for St Paul's Cathedral (grey: corridors to Westminster and the Tower). Blue, darker\n"
                "the more of it: where the dome is actually visible from street level, by line of sight across LiDAR."),
         "ru": ("Спокойная основа по мотивам OS Open Zoomstack Light (Ordnance Survey, OGL v3); здания и деревья LiDAR участвуют в лучах зрения,\nно не нарисованы. Парки, дороги, рельсы: Overture Maps (ODbL).",
                "парки", "коридоры к Вестминстеру и Тауэру", "5 км   ·   сетка 1 км, British National Grid",
                "Оранжевым: восемь коридоров видов, которые London View Management Framework охраняет для\n"
                "собора св. Павла (серым: коридоры к Вестминстеру и Тауэру). Синим, тем темнее, чем больше видно:\n"
                "откуда купол действительно виден с уровня улицы по лучу зрения поверх зданий и деревьев из LiDAR.")}


def halo_under(artist, halo):
    """Halo as its own text artist UNDER `artist` (a Text or an Annotation), then no path effects on the text itself.
    matplotlib strokes a multi-line label line by line, so a stroke path effect on the text lets the halo of line 2 eat
    the descenders of line 1 (j, g, y, p, д, у); same fix as shared/styles/common.halo_under. halo = (colour, linewidth)."""
    color, lw = halo
    ax = artist.axes
    x, y = artist.xyann if hasattr(artist, "xyann") else artist.get_position()
    ax.text(x, y, artist.get_text(), fontproperties=artist.get_fontproperties(), ha=artist.get_ha(), va=artist.get_va(),
            rotation=artist.get_rotation(), linespacing=artist._linespacing, color=color, zorder=artist.get_zorder() - 0.01,
            path_effects=[pe.Stroke(linewidth=lw, foreground=color)], clip_on=artist.get_clip_on())
    artist.set_path_effects([])
    return artist


def layer(name):
    try:
        return gpd.read_file(LAYERS, layer=name)
    except Exception:                     # noqa: BLE001
        return gpd.GeoDataFrame(geometry=[], crs=27700)


def figure(lang="en"):
    S.apply()
    t = S0.T[lang]
    stats = json.loads((S0.DER / "stats.json").read_text())
    with rasterio.open(S0.DER / "visible_level.tif") as d:
        lev = d.read(1); Tr, b = d.transform, d.bounds
    with rasterio.open(S0.DER / "ndsm_5m.tif") as d:
        ndsm = d.read(1).astype("float32") / 2
    g = S0.lvmf(); fp, _ = S0.stpauls_footprint(); wat = S0.water()
    parks, roads, rail = layer("parks"), layer("roads"), layer("rail")
    ax_x, ax_y = stats["dome_axis_bng"]
    body = rasterize([(fp.buffer(8), 1)], out_shape=lev.shape, transform=Tr, fill=0).astype(bool)
    water_mask = rasterize([(geom, 1) for geom in wat.geometry], out_shape=lev.shape, transform=Tr, fill=0).astype(bool)
    park_mask = rasterize([(geom, 1) for geom in parks.geometry], out_shape=lev.shape, transform=Tr, fill=0).astype(bool) if len(parks) else np.zeros(lev.shape, bool)
    cls = np.where(lev == 255, 0, S0.CLASS_OF_LEVEL[np.minimum(lev, 6)])
    open_ground = (ndsm < S0.OPEN_MAX) & ~body
    built = np.zeros(lev.shape + (4,), dtype="float32")                 # buildings (objects outside parks and water)
    built[~open_ground & ~water_mask & ~park_mask] = (*mpl.colors.to_rgb(P["building"]), 1.0)
    seen = np.zeros(lev.shape + (4,), dtype="float32")
    for k, c in CLS.items():
        seen[open_ground & (cls == k)] = (*mpl.colors.to_rgb(c), 1.0)
    seen[body] = (*mpl.colors.to_rgb(P["text"]), 1.0)

    W, H = 5.4, 6.75
    fig = plt.figure(figsize=(W, H))
    ext_w, ext_h = b.right - b.left, b.top - b.bottom
    rect = (0.07, 0.205, 0.86, 0.86 * W * (ext_h / ext_w) / H)
    ax = fig.add_axes(rect); ax.set_xlim(b.left, b.right); ax.set_ylim(b.bottom, b.top); ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(True); s.set_color(P["text"]); s.set_linewidth(0.8)
    ground(ax, P["land"])
    if len(parks):
        parks.plot(ax=ax, color=P["park"], edgecolor=P["park_edge"], lw=0.2, zorder=2)
    wat.plot(ax=ax, color=P["water"], lw=0, zorder=3.1)
    ext = (b.left, b.right, b.bottom, b.top)
    if len(roads):
        prim = roads[roads["class"].isin(["motorway", "trunk"])]; ab = roads[roads["class"].isin(["primary", "secondary"])]
        ab.plot(ax=ax, color=P["road"], lw=0.3, zorder=5.1)
        prim.plot(ax=ax, color=P["road_primary"], lw=0.55, zorder=5.3)
    if len(rail):
        rail.plot(ax=ax, color=P["rail"], lw=0.35, zorder=5.6)
    ax.imshow(seen, extent=ext, interpolation="antialiased", zorder=6)
    other = g[~g.stpauls]; sp = g[g.stpauls]
    other[other.TYPE == "VC"].boundary.plot(ax=ax, color=OTHER, lw=0.45, zorder=7)
    sp[sp.TYPE == "WSCA"].boundary.plot(ax=ax, color=CORR, lw=0.35, linestyle=(0, (2, 2)), zorder=7.1, alpha=0.8)
    sp[sp.TYPE == "VC"].plot(ax=ax, facecolor=mpl.colors.to_rgba(CORR, 0.25), edgecolor=CORR, lw=0.7, zorder=7.2)
    grid_lines(ax, 1000, color=P["grid"], lw=0.18, alpha=0.55, zorder=8)
    km_ticks(ax, 5000, color=P["text"], font=S.font("label", size=4.6), length=0.0, fmt=lambda v: f"{int(v // 1000) % 100:02d}")

    halo = (P["halo"], 1.8)
    pl = S0.places(g).sort_values("stpauls", ascending=False).drop_duplicates(subset="place")
    for _, v in pl.iterrows():
        name = t["places"].get(v.place, v.place); col = P["text"] if v.stpauls else "#6E6A60"
        ax.scatter([v.geometry.x], [v.geometry.y], s=12, facecolor=col, edgecolor=P["halo"], linewidth=0.5, zorder=9)
        if not name:
            continue
        dx, dy, ha = S0.OFFSETS.get(v.place, (300, 300, "left"))
        a = ax.annotate(name, (v.geometry.x, v.geometry.y), (v.geometry.x + dx, v.geometry.y + dy), ha=ha, va="center",
                        fontproperties=S.font("label", lang, 5.8), color=col, zorder=10, linespacing=1.15,
                        arrowprops=dict(arrowstyle="-", color=col, lw=0.4, shrinkA=0, shrinkB=2))
        halo_under(a, halo)
    ax.scatter([ax_x], [ax_y], s=50, facecolor="none", edgecolor=P["text"], linewidth=0.9, zorder=10)
    a = ax.annotate(t["stpauls"], (ax_x, ax_y), (ax_x + 500, ax_y + 700), ha="left", va="center", color=P["text"], zorder=10,
                    fontproperties=S.font("label_bold", lang, 6.6), arrowprops=dict(arrowstyle="-", color=P["text"], lw=0.5, shrinkA=0, shrinkB=4))
    halo_under(a, halo)
    for key, text in t["notes"]:
        (tx, ty), (px, py) = S0.NOTES[key]
        ax.annotate(text, (px, py), (tx, ty), ha="left", va="center", color=P["text"], zorder=11, linespacing=1.3,
                    fontproperties=S.font("label", lang, 5.3),
                    bbox=dict(boxstyle="square,pad=0.3", facecolor=P["halo"], edgecolor=P["text"], linewidth=0.4, alpha=0.95),
                    arrowprops=dict(arrowstyle="-", color=P["text"], lw=0.45, shrinkA=0, shrinkB=0))

    fig.text(0.07, 0.965, t["title"], fontproperties=S.font("title", lang), color=P["text"], va="top", ha="left")
    fig.text(0.07, 0.92, EXTRA[lang][4], fontproperties=S.font("subtitle", lang), color=P["muted"], va="top", ha="left", linespacing=1.35)
    in_blind = 100 * (1 - stats["vc_stpauls_open_sees_any_km2"] / stats["vc_stpauls_open_km2"])
    fig.text(0.07, 0.862, t["stats"].format(in_blind=S0.fmt(in_blind, lang), any=S0.fmt(stats["sees_any_km2"], lang, 1),
                                           out=S0.fmt(100 * stats["sees_any_outside_vc_share"], lang),
                                           whole=S0.fmt(stats["sees_whole_dome_km2"], lang, 1)),
             fontproperties=S.font("subtitle", lang, 6.6), color=CLS[3], va="top", ha="left", linespacing=1.4)
    # legend: two rows of swatches
    extra = EXTRA[lang]
    row1 = [(CLS[3], t["leg"][0][1]), (CLS[2], t["leg"][1][1]), (CLS[1], t["leg"][2][1])]
    row2 = [(P["park"], extra[1]), (P["water"], t["leg_water"]), ("pt", t["leg_pt"])]
    row3 = [("vc", t["leg_vc"]), ("ws", t["leg_ws"]), ("other", extra[2])]
    def swatches(items, y):
        x = 0.07
        for col, lab in items:
            if col == "vc":
                fig.patches.append(Rectangle((x, y), 0.028, 0.013, transform=fig.transFigure, facecolor=mpl.colors.to_rgba(CORR, 0.25), edgecolor=CORR, lw=0.7))
            elif col == "ws":
                fig.add_artist(Line2D([x, x + 0.028], [y + 0.0065] * 2, color=CORR, lw=0.6, linestyle=(0, (2, 2)), transform=fig.transFigure))
            elif col == "other":
                fig.add_artist(Line2D([x, x + 0.028], [y + 0.0065] * 2, color=OTHER, lw=0.6, transform=fig.transFigure))
            elif col == "pt":
                fig.add_artist(Line2D([x + 0.014], [y + 0.0065], marker="o", color="none", markerfacecolor=P["text"], markeredgecolor=P["halo"], markersize=3.2, transform=fig.transFigure))
            else:
                fig.patches.append(Rectangle((x, y), 0.028, 0.013, transform=fig.transFigure, facecolor=col, edgecolor="#B5B0A0", lw=0.4))
            tx = fig.text(x + 0.034, y + 0.0065, lab, va="center", ha="left", fontproperties=S.font("legend", lang, 5.2), color=P["text"])
            fig.canvas.draw()
            x = tx.get_window_extent(renderer=fig.canvas.get_renderer()).x1 / fig.bbox.width + 0.014
    swatches(row1, 0.181); swatches(row2, 0.160); swatches(row3, 0.139)
    scalebar_fig(fig, ax, 5000, extra[3], x=0.07, y=0.117, segments=5, color=P["text"], fill2=P["paper"], font=S.font("legend", lang, 5.0), height=0.006)
    src_lines = t["src"].split("\n")[:-1]                     # the series footer adds the analysis line itself
    S.footer(fig, "\n".join(src_lines) + "\n" + extra[0], day=5, lang=lang, x=0.07, y=0.018)
    out = HERE / f"map_{lang}_london.png"      # the day's main map_{lang}.png is the London-Paris comparison (paris/paris_apur.py)
    fig.savefig(out, dpi=300); plt.close(fig); print(out)


if __name__ == "__main__":
    for lang in (sys.argv[1:] or ["en", "ru"]):
        figure(lang)
