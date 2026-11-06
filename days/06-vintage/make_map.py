"""Day 6 (Vintage): Rotterdam, 14 May 1940. Buildings standing today by year of construction (BAG),
the 1940 fire boundary from the city's brandgrens lights, styled after 1930s Dutch topographic sheets.

    python fetch_data.py         # BAG, BGT water, brandgrens lights -> data/raw/
    python build_brandgrens.py   # lights -> line and zone (data/brandgrens_*.geojson)
    python make_map.py           # -> data/stats.json, data/survivors_top40.csv, map_en_old.png, map_ru_old.png
    python make_map_gemeentewerken.py   # -> the main maps map_en.png, map_ru.png

Style references only (nothing copied): Bonnebladen 1:25 000 of the 1930s as shown on Topotijdreis
(Kadaster; not open data, so no tiles are used) and the yellow brandgrens of the 1940 and 1955
municipal maps of the destroyed area.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import geopandas as gpd
import matplotlib as mpl
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from shapely.geometry import box
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
DATA = HERE / "data"
FONTS = HERE / "fonts"

X0, X1, Y0, Y1 = 91700, 95000, 435750, 438600       # RD New, metres
STANDING = ["Pand in gebruik", "Pand in gebruik (niet ingemeten)", "Verbouwing pand",
            "Pand buiten gebruik", "Sloopvergunning verleend"]

PAPER = "#efe4c8"
INK = "#2b2118"
INK2 = "#5a4a3a"
OLD_FILL = "#d9937f"      # built-up red of the 1930s sheets, for buildings that predate 1940
OLD_EDGE = "#8e3a2b"
NEW_FILL = "#e7dcc0"      # buildings of 1940 and later: barely there
NEW_EDGE = "#a4957b"
WATER = "#c3d3d3"
SHORE = "#56768c"
FIRE = "#e9bf2f"          # the yellow of the 1940 / 1955 brandgrens maps

T = {
    "en": {
        "title": "ROTTERDAM, 14 MAY 1940",
        "sub": "The fire line is still visible in today's building register. Inside it, {pin}% of the buildings\n"
               "standing now were built before 1940; within a kilometre outside it, {pout}%.",
        "leg_title": "LEGEND",
        "old": "built before 1940, still standing",
        "new": "built in 1940 or later",
        "fire": "brandgrens, the fire line: marked in the pavement\nsince 2010, {n} lights in the city register",
        "water": "water",
        "box": ("Bombing: 13:27–13:40. In ruins: 258 ha,\n"
                "25 000 homes and 11 000 other buildings;\n"
                "80 000 people homeless (Stadsarchief Rotterdam)."),
        "stats": ("Inside the line today: {n_in} buildings, {old_in} built before 1940\n"
                  "({pin}% of buildings, {fpin}% of footprint).\n"
                  "Within 1 km outside: {pout}% of buildings, {fpout}% of footprint.\n"
                  "Not all of the gap is the fire: survivors were also cleared\n"
                  "for the post-war plan (wederafbraak)."),
        "labels": {"stadhuis": "City hall", "post": "Post office", "beurs": "Beurs (exchange)", "laurens": "Laurenskerk",
                   "witte": "Witte Huis", "haring": "Haringvliet houses,\n1888–1898"},
        "places": {"maas": "N I E U W E   M A A S", "ndl": "NOORDEREILAND", "kral": "KRALINGEN", "west": "OUDE WESTEN",
                   "noord": "OUDE NOORDEN", "zuid": "KOP VAN ZUID"},
        "scale": "metres",
        "src": ("Data: BAG panden via PDOK (Kadaster, public domain), BGT water (PDOK, CC0), brandgrens lights from Gemeente Rotterdam "
                "public lighting WFS (public domain), all downloaded {d}.\nMethod: bouwjaar = original year of construction in BAG; line = {n} lights "
                "'Grondspot Medio type Brandgrens' joined to nearest neighbours, gaps where no lights are registered;\nzone closed through the river for "
                "counting. Facts: Stadsarchief Rotterdam. Style after 1930s Dutch topographic sheets. "
                "Analysis: Marija Ercegovac · #30DayMapChallenge day 6"),
    },
    "ru": {
        "title": "РОТТЕРДАМ, 14 МАЯ 1940",
        "sub": "Граница пожара до сих пор видна в реестре зданий. Внутри неё до 1940 года построены {pin}%\n"
               "нынешних домов, в километре снаружи {pout}%.",
        "leg_title": "УСЛОВНЫЕ ЗНАКИ",
        "old": "построено до 1940 года и стоит сейчас",
        "new": "построено в 1940 году и позже",
        "fire": "brandgrens, граница пожара: отмечена в мостовой\nс 2010 года, {n} светильников в реестре города",
        "water": "вода",
        "box": ("Бомбардировка: 13:27–13:40. В руинах 258 га,\n"
                "25 000 квартир и домов и 11 000 других зданий;\n"
                "80 000 человек без крова (Stadsarchief Rotterdam)."),
        "stats": ("Внутри линии сегодня стоят {n_in} здания, из них построены\n"
                  "до 1940 года {old_in} ({pin}% зданий, {fpin}% площади застройки).\n"
                  "В километре снаружи: {pout}% зданий, {fpout}% площади.\n"
                  "Пустота не только от пожара: уцелевшее после войны\n"
                  "тоже сносили под новый план (wederafbraak)."),
        "labels": {"stadhuis": "Ратуша", "post": "Почтамт", "beurs": "Биржа", "laurens": "Церковь\nСв. Лаврентия",
                   "witte": "Witte Huis", "haring": "Дома на Харингвлит,\n1888–1898"},
        "places": {"maas": "Н Ь И В Е-М А А С", "ndl": "НОРДЕРЭЙЛАНД", "kral": "КРАЛИНГЕН", "west": "АУДЕ-ВЕСТЕН",
                   "noord": "АУДЕ-НОРДЕН", "zuid": "КОП-ВАН-ЗЁЙД"},
        "scale": "метры",
        "src": ("Данные: BAG panden через PDOK (Kadaster, общественное достояние), вода BGT (PDOK, CC0), светильники brandgrens из WFS уличного освещения "
                "Gemeente Rotterdam (общественное достояние), выгрузка {d}.\nМетод: bouwjaar = год постройки по BAG; линия = {n} светильников "
                "«Grondspot Medio type Brandgrens», соединённых с ближайшими соседями, разрывы там, где светильников нет в реестре;\nдля подсчёта зона "
                "замкнута по реке. Факты: Stadsarchief Rotterdam. Стиль по голландским топокартам 1930-х. "
                "Расчёт: Мария Эрцеговац · #30DayMapChallenge день 6"),
    },
}

# landmarks: BAG pand id -> label key (all predate 1940 and stand inside the line)
LANDMARKS = {
    "0599100000701897": ("stadhuis", (-120, 25)),
    "0599100000767596": ("post", (-120, 0)),
    "0599100000617974": ("beurs", (-135, -25)),
    "0599100000702379": ("laurens", (60, 190)),
    "0599100000690521": ("witte", (-120, -170)),
    "0599100000631693": ("haring", (170, -230)),
}
PLACES = {  # key: (x, y, rotation, size, italic)
    "maas": (93520, 436660, 35, 15, True),
    "ndl": (93640, 436450, 35, 10.5, False),
    "kral": (94560, 438440, 0, 11, False),
    "west": (91960, 436880, 0, 11, False),
    "noord": (92950, 438480, 0, 11, False),
    "zuid": (94380, 436120, 0, 10.5, False),
}
WATER_NAMES = {  # small italic labels, Dutch names as on the old sheets
    "Leuvehaven": (92880, 436720, 90), "Wijnhaven": (93120, 436960, 22), "Oude Haven": (93515, 437015, 0),
    "Haringvliet": (93700, 437215, 12), "Boerengat": (94130, 437240, 12), "Koningshaven": (94080, 436380, 35),
    "Rotte": (93010, 437990, 70), "Rijnhaven": (93180, 435960, 0),
}


def setup_fonts():
    for f in FONTS.glob("OldStandard-*.ttf"):
        fm.fontManager.addfont(str(f))
    mpl.rcParams.update({"font.family": "Old Standard TT", "text.color": INK, "hatch.linewidth": 0.5})


def load():
    b = gpd.read_file(RAW / "bag_pand.gpkg", bbox=(X0 - 1200, Y0 - 1200, X1 + 1200, Y1 + 1200))
    b = b[b["status"].isin(STANDING) & b["bouwjaar"].between(1000, 2030)].copy()
    w = gpd.read_file(RAW / "bgt_waterdeel.gpkg", bbox=(X0 - 200, Y0 - 200, X1 + 200, Y1 + 200))
    w = w[w["eind_registratie"].isna()]
    water = unary_union(w.geometry.values).intersection(box(X0 - 100, Y0 - 100, X1 + 100, Y1 + 100))
    zone = gpd.read_file(DATA / "brandgrens_zone.geojson")
    line = gpd.read_file(DATA / "brandgrens_line.geojson")
    lights = gpd.read_file(DATA / "brandgrens_lights.geojson")
    return b, water, zone, line, lights


def stats(b, zone, n_lights):
    Z = unary_union(zone.geometry.values)
    pt = b.geometry.representative_point()
    inside = pt.within(Z)
    ring = pt.within(Z.buffer(1000).difference(Z))
    fa = b.area

    def share(mask):
        s = b[mask]
        old = s["bouwjaar"] < 1940
        mid = s["bouwjaar"].between(1940, 1965)
        return {"n": int(len(s)), "old": int(old.sum()), "pct_old": round(100 * old.mean(), 1),
                "pct_old_footprint": round(100 * fa[mask][old.values].sum() / fa[mask].sum(), 1),
                "pct_1940_1965": round(100 * mid.mean(), 1),
                "pct_1940_1965_footprint": round(100 * fa[mask][mid.values].sum() / fa[mask].sum(), 1)}
    st = {"inside": share(inside), "ring_1km": share(ring), "lights": int(n_lights),
          "zone_area_ha_incl_water": round(Z.area / 1e4, 1)}
    f = DATA / "stats.json"
    disk = json.loads(f.read_text()) if f.exists() else {}
    disk.update(st)                     # keep keys added by analysis.py and make_web.py
    f.write_text(json.dumps(disk, indent=1, ensure_ascii=False))
    return st, inside


def survivors(b, inside, top=40):
    """Pre-1940 buildings inside the line, largest first, with their BAG addresses (PDOK WFS)."""
    out = DATA / "survivors_top40.csv"
    if out.exists():
        return
    import requests
    s = b[inside.values & (b["bouwjaar"] < 1940).values].copy()
    s["fa"] = s.area
    rows = []
    for _, r in s.sort_values("fa", ascending=False).head(top).iterrows():
        c = r.geometry.centroid
        d = requests.get("https://service.pdok.nl/lv/bag/wfs/v2_0", timeout=60, params={
            "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": "bag:verblijfsobject",
            "outputFormat": "application/json", "count": 200,
            "bbox": f"{c.x - 60},{c.y - 60},{c.x + 60},{c.y + 60},urn:ogc:def:crs:EPSG::28992"}).json()
        adr = sorted({f"{q['openbare_ruimte']} {q['huisnummer']}{q.get('huisletter') or ''}"
                      for q in (f["properties"] for f in d["features"])
                      if r["identificatie"] in str(q.get("pandidentificatie"))})
        rows.append((r["identificatie"], r["bouwjaar"], int(r["fa"]), int(c.x), int(c.y),
                     "; ".join(adr[:3]) + (f" (+{len(adr) - 3})" if len(adr) > 3 else "")))
    pd.DataFrame(rows, columns=["pand", "bouwjaar", "footprint_m2", "x", "y", "addresses"]).to_csv(out, index=False)


def paper(fig):
    rng = np.random.default_rng(1940)
    h, w = 600, 480
    noise = rng.normal(0, 1, (h, w))
    from scipy.ndimage import gaussian_filter
    tex = gaussian_filter(noise, 1.2) * 0.5 + gaussian_filter(rng.normal(0, 1, (h, w)), 18) * 2.2
    yy, xx = np.mgrid[0:h, 0:w]
    vign = ((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2)
    base = np.array(mpl.colors.to_rgb(PAPER))
    img = base[None, None, :] * (1 + 0.012 * tex[..., None] - 0.10 * vign[..., None])
    ax = fig.add_axes([0, 0, 1, 1], zorder=-10)
    ax.imshow(np.clip(img, 0, 1), extent=[0, 1, 0, 1], aspect="auto", interpolation="bicubic")
    ax.set_axis_off()


def waterlines(ax, water):
    for k, d in enumerate((7, 16, 28, 44)):
        inner = water.buffer(-d, join_style=2)
        if inner.is_empty:
            continue
        gs = gpd.GeoSeries([inner.boundary])
        gs.plot(ax=ax, color=SHORE, lw=0.35 - 0.05 * k, alpha=0.55 - 0.1 * k, zorder=2)


def scalebar(ax, lang):
    x, y = X0 + 120, Y0 + 110
    ax.add_patch(Rectangle((x - 70, y - 50), 1300, 190, facecolor=PAPER, edgecolor="none", alpha=0.9, zorder=7.5))
    for i, (a, c) in enumerate([(0, INK), (100, PAPER), (200, INK), (300, PAPER), (400, INK)]):
        ax.add_patch(Rectangle((x + a, y), 100, 22, facecolor=c, edgecolor=INK, lw=0.6, zorder=8))
    ax.add_patch(Rectangle((x + 500, y), 500, 22, facecolor=PAPER, edgecolor=INK, lw=0.6, zorder=8))
    for v in (0, 500, 1000):
        ax.text(x + v, y + 45, f"{v}", ha="center", va="bottom", fontsize=8, zorder=8)
    ax.text(x + 1060, y + 11, T[lang]["scale"], ha="left", va="center", fontsize=8, style="italic", zorder=8)


def north(ax):
    x, y = X1 - 140, 436780
    ax.annotate("", xy=(x, y + 210), xytext=(x, y), zorder=8,
                arrowprops=dict(arrowstyle="-|>,head_length=1.1,head_width=0.45", lw=1.0, color=INK))
    ax.text(x, y + 245, "N", ha="center", va="bottom", fontsize=12, fontweight="bold", zorder=8)


def neatline(fig, ax):
    pos = ax.get_position()
    for pad, lw in ((0.0, 0.6), (0.006, 1.8)):
        fig.add_artist(Rectangle((pos.x0 - pad, pos.y0 - pad * 0.8), pos.width + 2 * pad, pos.height + 1.6 * pad,
                                 transform=fig.transFigure, fill=False, edgecolor=INK, lw=lw, zorder=20))
    # RD kilometre ticks, as on the sheets of the Rijksdriehoeksmeting
    for xk in range(92000, X1, 1000):
        ax.plot([xk, xk], [Y1, Y1 - 45], color=INK, lw=0.7, zorder=9, clip_on=False)
        ax.plot([xk, xk], [Y0, Y0 + 45], color=INK, lw=0.7, zorder=9, clip_on=False)
        ax.text(xk, Y1 + 30, f"{xk // 1000}", ha="center", va="bottom", fontsize=8, color=INK2)
    for yk in range(436000, Y1, 1000):
        ax.plot([X0, X0 + 45], [yk, yk], color=INK, lw=0.7, zorder=9, clip_on=False)
        ax.plot([X1, X1 - 45], [yk, yk], color=INK, lw=0.7, zorder=9, clip_on=False)
        ax.text(X0 - 30, yk, f"{yk // 1000}", ha="right", va="center", fontsize=8, color=INK2)


def halo_text(ax, x, y, text, lw=2.6, zorder=10, **kw):
    """Halo as its own artist under the text: matplotlib strokes multi-line text line by line, so a withStroke halo of
    line 2 eats the descenders of line 1 (shared/styles/common.py halo_under, same fix)."""
    kw2 = {k: v for k, v in kw.items() if k != "color"}
    ax.text(x, y, text, color=PAPER, zorder=zorder - 0.01, path_effects=[pe.Stroke(linewidth=lw, foreground=PAPER)], **kw2)
    return ax.text(x, y, text, zorder=zorder, **kw)


def halo_annotate(ax, text, xy, xytext, lw=2.6, zorder=11, **kw):
    """The same for a label with a leader line: the halo copy carries no arrow."""
    kw2 = {k: v for k, v in kw.items() if k not in ("color", "arrowprops")}
    ax.annotate(text, xy=xy, xytext=xytext, color=PAPER, zorder=zorder - 0.01,
                path_effects=[pe.Stroke(linewidth=lw, foreground=PAPER)], **kw2)
    return ax.annotate(text, xy=xy, xytext=xytext, zorder=zorder, **kw)


def render(lang, b, water, zone, line, lights, st):
    t = T[lang]
    FW, FH = 12.0, 13.5
    fig = plt.figure(figsize=(FW, FH), dpi=200)
    paper(fig)
    W, H = X1 - X0, Y1 - Y0
    aw = 0.88
    ah = aw * FW * H / W / FH
    map_top = 1 - 1.45 / FH
    ax = fig.add_axes([0.06, map_top - ah, aw, ah])
    ax.set_xlim(X0, X1)
    ax.set_ylim(Y0, Y1)
    ax.set_aspect("equal")
    ax.set_axis_off()

    gpd.GeoSeries([water]).plot(ax=ax, color=WATER, lw=0, zorder=1)
    waterlines(ax, water)
    gpd.GeoSeries([water.boundary]).plot(ax=ax, color=SHORE, lw=0.7, zorder=3)
    new = b[b["bouwjaar"] >= 1940]
    old = b[b["bouwjaar"] < 1940]
    new.plot(ax=ax, facecolor=NEW_FILL, edgecolor=NEW_EDGE, lw=0.25, zorder=4)
    old.plot(ax=ax, facecolor=OLD_FILL, edgecolor=OLD_EDGE, lw=0.3, zorder=5)
    line.plot(ax=ax, color=FIRE, lw=5.0, alpha=0.85, zorder=6, capstyle="round")
    line.plot(ax=ax, color=INK, lw=0.7, linestyle=(0, (4, 2.5)), zorder=7)
    ax.scatter(lights.geometry.x, lights.geometry.y, s=1.6, color=INK, zorder=7, lw=0)

    for key, (x, y, rot, size, it) in PLACES.items():
        kw = dict(rotation=rot, fontsize=size, ha="center", va="center", style="italic" if it else "normal",
                  color=SHORE if it else INK2, rotation_mode="anchor")
        if it:
            ax.text(x, y, t["places"][key], zorder=10, **kw)
        else:
            halo_text(ax, x, y, t["places"][key], zorder=10, **kw)
    for name, (x, y, rot) in WATER_NAMES.items():
        ax.text(x, y, name, rotation=rot, fontsize=7.5, style="italic", color=SHORE, ha="center", va="center",
                zorder=10, rotation_mode="anchor")
    for pid, (key, (dx, dy)) in LANDMARKS.items():
        row = b[b["identificatie"] == pid]
        if row.empty:
            continue
        c = row.geometry.iloc[0].representative_point()
        halo_annotate(ax, t["labels"][key], (c.x, c.y), (c.x + dx, c.y + dy), fontsize=8.5, color=INK,
                      ha="right" if dx < 0 else "left", va="center", zorder=11,
                      arrowprops=dict(arrowstyle="-", lw=0.5, color=INK, shrinkA=1, shrinkB=2))

    scalebar(ax, lang)
    north(ax)
    neatline(fig, ax)

    # title block
    fig.text(0.5, 1 - 0.5 / FH, t["title"], ha="center", va="center", fontsize=30, fontweight="bold", color=INK)
    fig.text(0.5, 1 - 1.0 / FH, t["sub"].format(pin=round(st["inside"]["pct_old"]), pout=round(st["ring_1km"]["pct_old"])),
             ha="center", va="center", fontsize=12, color=INK2, linespacing=1.4)

    # legend and boxes under the map
    y_top = map_top - ah - 0.33 / FH
    fig.text(0.06, y_top, t["leg_title"], fontsize=10.5, fontweight="bold", va="top", color=INK)
    handles = [Patch(facecolor=OLD_FILL, edgecolor=OLD_EDGE, lw=0.6, label=t["old"]),
               Patch(facecolor=NEW_FILL, edgecolor=NEW_EDGE, lw=0.6, label=t["new"]),
               Line2D([0], [0], color=FIRE, lw=6, label=t["fire"].format(n=st["lights"])),
               Patch(facecolor=WATER, edgecolor=SHORE, lw=0.6, label=t["water"])]
    leg = fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.055, y_top - 0.012), frameon=False,
                     fontsize=9.5, handlelength=2.6, handleheight=1.3, labelspacing=0.9, borderaxespad=0)
    # overlay the dashed centreline on the brandgrens legend handle
    leg_line = leg.get_lines()[0] if leg.get_lines() else None
    if leg_line is not None:
        leg_line.set_path_effects([pe.Stroke(linewidth=6, foreground=FIRE), pe.Normal()])
        leg_line.set_color(INK)
        leg_line.set_linewidth(0.8)
        leg_line.set_linestyle((0, (4, 2.5)))
    s_in, s_out = st["inside"], st["ring_1km"]
    sep = "\u00a0" if lang == "ru" else ","
    stats_txt = t["stats"].format(n_in=f"{s_in['n']:,}".replace(",", sep), old_in=s_in["old"], pin=round(s_in["pct_old"]),
                                  fpin=round(s_in["pct_old_footprint"]), pout=round(s_out["pct_old"]),
                                  fpout=round(s_out["pct_old_footprint"]))
    fig.text(0.47, y_top, stats_txt, fontsize=9.5, va="top", ha="left", color=INK, linespacing=1.45)
    fig.text(0.47, y_top - 1.32 / FH, t["box"], fontsize=9.5, va="top", ha="left", color=INK2, linespacing=1.45,
             style="italic")
    fig.text(0.06, 0.3 / FH, t["src"].format(d=DOWNLOADED, n=st["lights"]), fontsize=7.2, color=INK2, va="bottom",
             ha="left", linespacing=1.5)
    out = HERE / f"map_{lang}_old.png"            # first version, kept since the series moved to local styles
    fig.savefig(out, dpi=200, facecolor=PAPER)
    plt.close(fig)
    # archival copy: a 256-colour palette keeps the flat fills and halves the file for the public repository
    from PIL import Image
    Image.open(out).convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(out, optimize=True)
    print("->", out)


def downloaded_date():
    note = RAW / "downloaded.json"
    if note.exists():
        stamps = json.loads(note.read_text()).values()
        return min(stamps)[:10]
    return date.today().isoformat()


DOWNLOADED = None


def main():
    global DOWNLOADED
    setup_fonts()
    DOWNLOADED = downloaded_date()
    b, water, zone, line, lights = load()
    st, inside = stats(b, zone, len(lights))
    survivors(b, inside)
    print(json.dumps(st, indent=1))
    for lang in ("en", "ru"):
        render(lang, b, water, zone, line, lights, st)


if __name__ == "__main__":
    main()
