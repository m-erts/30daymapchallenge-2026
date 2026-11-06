"""Day 6, the main map (since 04.11.2026): in the manner of Gemeentewerken Rotterdam 1940–1955, the city's own maps of
the bombing and the rebuilding (shared/styles/nl_rotterdam.py: palette sampled from the 1940 GTD plan with the
brandgrens and the 1955 "Oud en nieuw Rotterdam", both public domain on Wikimedia Commons; Jost for the spaced
capitals of the Futura / Nobel class; an Isotype inset). Three classes instead of two: before 1940, 1940–1965
(wederopbouw), after 1965.

    python make_map_gemeentewerken.py      # after make_map.py; -> map_en.png, map_ru.png

The first version (1930s Bonneblad manner, Old Standard TT) is kept as map_en_old.png / map_ru_old.png by make_map.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib.lines as ml
import matplotlib.patches as mp
import matplotlib.pyplot as plt
from shapely.geometry import box

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))          # repository root, for shared/styles

import make_map as M                                          # noqa: E402  (data loading and statistics)
from shared.styles import nl_rotterdam as R                   # noqa: E402
from shared.styles.common import paper, scalebar, water_label_point   # noqa: E402

# Day 6: the three building periods pulled apart by lightness (Masha, 06.11.2026: "very clear and readable by period").
# Worst-case CIEDE2000 between periods, paper and water, also simulated for deutan/protan vision: 12.2 (was 4.7:
# "after 1965" #D6C087 nearly vanished into the paper, ochre and brick were close). Process-local override of the
# shared nl_rotterdam palette; nothing else in the style changes.
R.PALETTE.update(spared="#7A4E12", new="#DA6A2A", built_1940="#A8977A")
P = R.PALETTE
T = {
    "en": {
        "title": "Rotterdam, 14 May 1940",
        "kicker": "What the fire left in today's building register",
        "sub": "Inside the brandgrens {pin}% of the buildings standing now predate 1940 and {pmid}% date from the rebuilding of\n"
               "1940–1965; within a kilometre outside, {pout}% predate 1940.",
        "key": "KEY:",
        "items": ["built before 1940, still standing", "built 1940–1965 (wederopbouw, the rebuilding)", "built after 1965", "water"],
        "fire": "yellow line: the brandgrens, marked\nin the pavement with lights since 2010",
        "iso": "25 000 HOMES DESTROYED · 1 HOUSE = 1 000\n13:27–13:40 · 258 HA IN RUINS (STADSARCHIEF ROTTERDAM)",
        "iso_note": "Isotype: count, not size (after Neurath and Arntz, The Hague 1934–40)",
        "stats": "Inside the line: {n_in} buildings, {old_in} built before 1940\n({pin}% of buildings, {fpin}% of the footprint).\n"
                 "Within 1 km outside: {pout}% of buildings, {fpout}% of the footprint.\n"
                 "Not all of the gap is the fire: survivors were also\ncleared for the post-war plan (wederafbraak).",
        "places": {"west": "Oude Westen", "kral": "Kralingen", "ndl": "Noordereiland", "zuid": "Kop van Zuid", "noord": "Oude Noorden"},
        "maas": "Nieuwe Maas",
        "labels": {"stadhuis": "City hall", "post": "Post office", "beurs": "Beurs", "laurens": "Laurenskerk", "witte": "Witte Huis"},
        "scale": "1 km",
        "src": "Data: BAG panden via PDOK (Kadaster, public domain), BGT water (PDOK, CC0), brandgrens lights from the\n"
               "Gemeente Rotterdam street-lighting register (public domain), downloaded {d}. Facts: Stadsarchief Rotterdam.\n"
               "Style after the Gemeentewerken Rotterdam maps of 1940 and 1955 (Wikimedia Commons, public domain).",
    },
    "ru": {
        "title": "Роттердам, 14 мая 1940",
        "kicker": "Что пожар оставил в нынешнем реестре зданий",
        "sub": "Внутри brandgrens до 1940 года построены {pin}% нынешних зданий, {pmid}% — в годы восстановления\n"
               "1940–1965; в километре снаружи довоенных {pout}%.",
        "key": "УСЛОВНЫЕ ЗНАКИ:",
        "items": ["построено до 1940 года, стоит сейчас", "построено в 1940–1965 (wederopbouw, восстановление)", "построено после 1965",
                  "вода"],
        "fire": "жёлтая линия: brandgrens, с 2010 года\nотмечена в мостовой светильниками",
        "iso": "25 000 ЖИЛИЩ РАЗРУШЕНО · 1 ДОМИК = 1 000\n13:27–13:40 · 258 ГА В РУИНАХ (STADSARCHIEF ROTTERDAM)",
        "iso_note": "Изотип: количество знаками, а не размером (по Нейрату и Арнцу, Гаага, 1934–1940)",
        "stats": "Внутри линии сегодня {n_in} здания, из них до 1940 года {old_in}\n({pin}% зданий, {fpin}% площади застройки).\n"
                 "В километре снаружи: {pout}% зданий, {fpout}% площади.\n"
                 "Пустота не только от пожара: уцелевшее после войны\nтоже сносили под новый план (wederafbraak).",
        "places": {"west": "Ауде-Вестен", "kral": "Кралинген", "ndl": "Нордерэйланд", "zuid": "Коп-ван-Зёйд", "noord": "Ауде-Норден"},
        "maas": "Ньиве-Маас",
        "labels": {"stadhuis": "Ратуша", "post": "Почтамт", "beurs": "Биржа", "laurens": "Laurenskerk", "witte": "Witte Huis"},
        "scale": "1 км",
        "src": "Данные: BAG panden через PDOK (Kadaster, общественное достояние), вода BGT (PDOK, CC0),\n"
               "светильники brandgrens из реестра уличного освещения Gemeente Rotterdam (общественное достояние),\n"
               "выгрузка {d}. Факты: Stadsarchief Rotterdam. Стиль по картам Gemeentewerken Rotterdam\n"
               "1940 и 1955 годов (Wikimedia Commons, общественное достояние).",
    },
}
PLACES = {"west": (92160, 436880), "kral": (94560, 438300), "ndl": (93640, 436470), "zuid": (94380, 436120), "noord": (92950, 438330)}
MAAS = (93860, 436870, 27)                         # x, y, rotation: the channel north of the Noordereiland
LANDMARKS = {"0599100000701897": ("stadhuis", (-140, 30)), "0599100000767596": ("post", (-140, 0)),
             "0599100000617974": ("beurs", (-150, -30)), "0599100000702379": ("laurens", (60, 170)),
             "0599100000690521": ("witte", (-130, -160))}


def spaced(s: str) -> str:
    return " ".join(s.upper()).replace("   ", "     ")


def render(lang, b, water, line, st):
    t = T[lang]
    fig, ax = R.figure()
    ax.set_position([0.06, 0.30, 0.88, 0.555])        # a little lower than the style default: room for two subtitle lines
    paper(fig, P["paper"], grain=0.02, fibre=0.01)
    frame = gpd.GeoDataFrame(geometry=[box(M.X0, M.Y0, M.X1, M.Y1)], crs=28992)
    L = {"water": gpd.GeoDataFrame(geometry=[water], crs=28992), "buildings": b, "brandgrens": line}
    R.basemap(ax, L, frame)
    for s in ax.spines.values():
        s.set_visible(True)
        s.set_color(P["text"])
        s.set_linewidth(0.5)
    ax.set_axis_on()
    ax.set_xticks([])
    ax.set_yticks([])
    f = lambda role, size=None: R.font(role, lang, size)          # noqa: E731

    # water and districts in spaced capitals; landmarks small with leader lines
    ax.text(MAAS[0], MAAS[1], spaced(t["maas"]), fontproperties=f("water"), color=P["water_text"], rotation=MAAS[2],
            ha="center", va="center", zorder=20, clip_on=True, rotation_mode="anchor")
    for k, (x, y) in PLACES.items():
        R.label(ax, x, y, spaced(t["places"][k]), kind="district", lang=lang, halo=P["paper"], halo_width=1.6)
    import matplotlib.patheffects as pe
    for pid, (k, (dx, dy)) in LANDMARKS.items():
        row = b[b["identificatie"] == pid]
        if row.empty:
            continue
        c = row.geometry.iloc[0].representative_point()
        common = dict(fontproperties=f("label", 4.4), ha="right" if dx < 0 else "left", va="center")
        # halo as its own artist under the text (multi-line safe, as halo_under in shared/styles/common.py)
        ax.annotate(t["labels"][k].upper(), xy=(c.x, c.y), xytext=(c.x + dx, c.y + dy), color=P["paper"], zorder=21.99,
                    path_effects=[pe.Stroke(linewidth=1.4, foreground=P["paper"])], **common)
        ax.annotate(t["labels"][k].upper(), xy=(c.x, c.y), xytext=(c.x + dx, c.y + dy), color=P["text"], zorder=22,
                    arrowprops=dict(arrowstyle="-", lw=0.35, color=P["text"], shrinkA=0.5, shrinkB=1), **common)
    ax.add_patch(mp.Rectangle((0.025, 0.02), 0.36, 0.085, transform=ax.transAxes, facecolor=P["legend_paper"],
                              edgecolor=P["text"], lw=0.4, zorder=28))
    scalebar(ax, 1000, t["scale"], x=0.045, y=0.04, color=P["text"], font=f("label", 4.6), segments=4,
             fill2=P["legend_paper"], height=0.008, lw=0.8)

    # title block and north arrow
    fig.text(0.06, 0.955, spaced(t["title"]), fontproperties=f("title", 13.5), color=P["text"], va="top")
    fig.text(0.06, 0.912, spaced(t["kicker"]), fontproperties=f("subtitle", 5.6), color=P["text"], va="top")
    sin, sout = st["inside"], st["ring_1km"]
    fig.text(0.06, 0.893, t["sub"].format(pin=round(sin["pct_old"]), pmid=round(sin["pct_1940_1965"]), pout=round(sout["pct_old"])),
             fontproperties=f("body", 5.3), color=P["muted"], va="top", linespacing=1.4)
    R.north_arrow(fig, 0.905, 0.928, 0.03, P["text"])

    # boxed key (VERKLARING in the originals)
    fig.add_artist(mp.Rectangle((0.06, 0.105), 0.44, 0.18, transform=fig.transFigure, facecolor=P["legend_paper"],
                                edgecolor=P["text"], lw=0.6))
    fig.text(0.075, 0.272, t["key"], fontproperties=f("label_bold", 5.6), color=P["text"], va="top")
    cols = [P["spared"], P["new"], P["built_1940"], P["water"]]
    for i, (col, name) in enumerate(zip(cols, t["items"])):
        yy = 0.243 - i * 0.026
        fig.add_artist(mp.Rectangle((0.075, yy - 0.007), 0.03, 0.014, transform=fig.transFigure, facecolor=col,
                                    edgecolor=P["line"], lw=0.4))
        fig.text(0.115, yy, name.upper(), fontproperties=f("legend", 4.5), color=P["text"], va="center")
    yy = 0.243 - 4 * 0.026
    fig.add_artist(ml.Line2D([0.075, 0.105], [yy, yy], color=P["fire_casing"], lw=2.6, transform=fig.transFigure))
    fig.add_artist(ml.Line2D([0.075, 0.105], [yy, yy], color=P["fire"], lw=1.6, transform=fig.transFigure))
    fig.text(0.115, yy, t["fire"].upper(), fontproperties=f("legend", 4.3), color=P["text"], va="center", linespacing=1.3)

    # Isotype inset and the numbers
    R.isotype_row(fig, 0.53, 0.262, 25, 1000, color=P["new"], caption="")
    fig.text(0.53, 0.222, t["iso"], fontproperties=f("legend", 4.6), color=P["text"], va="top", linespacing=1.45)
    sep = " " if lang == "ru" else ","
    fig.text(0.53, 0.185, t["stats"].format(n_in=f"{sin['n']:,}".replace(",", sep), old_in=sin["old"], pin=round(sin["pct_old"]),
                                            fpin=round(sin["pct_old_footprint"]), pout=round(sout["pct_old"]),
                                            fpout=round(sout["pct_old_footprint"])),
             fontproperties=f("body", 4.6), color=P["text"], va="top", linespacing=1.45)
    note_font = f("credit", 4.6) if lang == "en" else f("body", 4.4)
    fig.text(0.53, 0.112, t["iso_note"], fontproperties=note_font, color=P["muted"], va="center")

    R.footer(fig, t["src"].format(d=M.downloaded_date()), day=6, lang=lang, y=0.022)
    out = HERE / f"map_{lang}.png"
    fig.savefig(out)
    plt.close(fig)
    print("->", out)


def main():
    b, water, zone, line, lights = M.load()
    st = json.loads((M.DATA / "stats.json").read_text())
    for lang in ("en", "ru"):
        render(lang, b, water, line, st)


if __name__ == "__main__":
    main()
