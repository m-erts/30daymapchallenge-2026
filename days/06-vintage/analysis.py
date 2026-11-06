"""Day 6: the analytical layer and the checks behind the map, aggregated in DuckDB SQL.

    python analysis.py      # after make_map.py (it reads the buildings and the zone, and adds to data/stats.json)

1. Robustness of the headline (share of today's buildings that predate 1940, inside the fire line against outside):
   - comparison rings 0–500 m, 0–1 km and 1–2 km outside the zone;
   - the zone shrunk by 50 m, so that buildings near the uncertain edge do not count;
   - the zone taken from the city's own map of May 1940 (spots shaded as destroyed) instead of the 2010 lights.
2. Heritage: rijksmonumenten (Rijksdienst voor het Cultureel Erfgoed, via PDOK, CC BY 4.0) joined to the BAG building
   they stand in, so each monument gets the BAG year of construction; counts by zone and period, with the year the
   monument was designated. Question: inside the fire line, is the protected heritage itself post-war?

Writes data/stats.json (key "analysis") and data/monuments.csv.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import requests
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_map as M          # noqa: E402  (buildings and zone, exactly as on the map)
import make_web as W          # noqa: E402  (reading of the 1940 map under each building)

RAW = HERE / "data" / "raw"
DATA = HERE / "data"
RCE_WFS = "https://service.pdok.nl/rce/ps-ch/wfs/v1_0"
UA = {"User-Agent": "30DayMapChallenge-2026 day 6 (research)"}


def fetch_monuments():
    out = RAW / "rce_rijksmonumenten_points.geojson"
    if not out.exists():
        x0, y0, x1, y1 = 89500, 434500, 96000, 439500
        r = requests.get(RCE_WFS, headers=UA, timeout=120, params={
            "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": "ps-ch:rce_inspire_points",
            "outputFormat": "application/json", "srsName": "EPSG:28992", "count": 5000,
            "bbox": f"{x0},{y0},{x1},{y1},urn:ogc:def:crs:EPSG::28992"})
        r.raise_for_status()
        out.write_bytes(r.content)
    g = gpd.read_file(out)
    g["monument_nr"] = g["ciCitation"].str.rsplit("/", n=1).str[-1]
    g["designated"] = pd.to_datetime(g["legalfoundationdate"], errors="coerce").dt.year
    g = g.rename(columns={"text": "name"})
    return g[["monument_nr", "name", "designated", "ciCitation", "geometry"]].set_crs(28992, allow_override=True)


def zones(b, zone):
    Z = unary_union(zone.geometry.values)
    pt = b.geometry.representative_point()
    out = pd.DataFrame({"inside": pt.within(Z).values,
                        "inside_shrunk": pt.within(Z.buffer(-50)).values,
                        "ring_0_500": pt.within(Z.buffer(500).difference(Z)).values,
                        "ring_0_1000": pt.within(Z.buffer(1000).difference(Z)).values,
                        "ring_1000_2000": pt.within(Z.buffer(2000).difference(Z.buffer(1000))).values})
    g = W.georef_1940()
    out["c40"] = W.read_1940(W.classes_1940(g), g, pt.x.values, pt.y.values)
    return out


def main():
    b, water, zone, line, lights = M.load()
    b = b.reset_index(drop=True)
    z = zones(b, zone)
    t = pd.DataFrame({"pand": b["identificatie"], "y": b["bouwjaar"].astype(int), "fa": b.area.values}).join(z)
    con = duckdb.connect()
    con.register("t", t)

    def share(where):
        r = con.execute(f"""
            SELECT count(*) AS n,
                   round(100 * avg(CASE WHEN y < 1940 THEN 1 ELSE 0 END), 1) AS pct_old,
                   round(100 * sum(CASE WHEN y < 1940 THEN fa ELSE 0 END) / sum(fa), 1) AS pct_old_fa,
                   round(100 * avg(CASE WHEN y BETWEEN 1940 AND 1965 THEN 1 ELSE 0 END), 1) AS pct_wederopbouw
            FROM t WHERE {where}""").fetchone()
        return dict(zip(["n", "pct_old", "pct_old_footprint", "pct_1940_1965"], r))

    robust = {
        "inside_line": share("inside"),
        "inside_line_minus_50m": share("inside_shrunk"),
        "ring_0_500m": share("ring_0_500"),
        "ring_0_1km": share("ring_0_1000"),
        "ring_1_2km": share("ring_1000_2000"),
        "destroyed_on_1940_map": share("c40 = 1"),
        "outside_1940_destroyed_area_within_extent": share("c40 = 0 AND NOT inside"),
    }

    # heritage: each monument point -> the BAG building it stands in (or the nearest within 15 m)
    mon = fetch_monuments()
    bb = b[["identificatie", "bouwjaar", "geometry"]]
    j = gpd.sjoin_nearest(mon, bb, how="left", max_distance=15, distance_col="dist_m")
    j = j.sort_values("dist_m").drop_duplicates("monument_nr")
    Zg = unary_union(zone.geometry.values)
    j["inside"] = j.geometry.within(Zg)
    j["ring_0_1000"] = j.geometry.within(Zg.buffer(1000).difference(Zg))
    j["period"] = pd.cut(j["bouwjaar"], [0, 1939, 1965, 3000], labels=["before 1940", "1940-1965", "after 1965"]).astype(str)
    j.loc[j["bouwjaar"].isna(), "period"] = "no BAG building"
    m = pd.DataFrame(j.drop(columns="geometry"))
    con.register("m", m)
    rows = con.execute("""
        SELECT CASE WHEN inside THEN 'inside line' WHEN ring_0_1000 THEN 'ring 0-1 km' ELSE 'elsewhere' END AS zone,
               period, count(*) AS monuments, median(designated) AS median_year_designated,
               min(designated) AS first_designated
        FROM m GROUP BY ALL ORDER BY zone, period""").df()
    heritage = {}
    for zname, grp in rows.groupby("zone"):
        tot = int(grp["monuments"].sum())
        heritage[zname] = {"monuments": tot,
                           "by_period": {r.period: {"n": int(r.monuments), "pct": round(100 * r.monuments / tot, 1),
                                                    "median_year_designated": None if pd.isna(r.median_year_designated)
                                                    else int(r.median_year_designated)}
                                         for r in grp.itertuples()}}
    # strict reading: a post-war monument designated in 1973 is almost certainly a point placed on a neighbouring building
    strict = con.execute("""
        SELECT count(*) FILTER (WHERE inside AND period = '1940-1965' AND designated >= 2000) AS inside_postwar_strict,
               count(*) FILTER (WHERE inside AND period = '1940-1965') AS inside_postwar,
               count(*) FILTER (WHERE inside) AS inside_all,
               count(*) FILTER (WHERE ring_0_1000 AND period = '1940-1965') AS ring_postwar,
               count(*) FILTER (WHERE ring_0_1000) AS ring_all
        FROM m""").df().iloc[0].astype(int).to_dict()
    postwar_inside = con.execute("SELECT count(*) FROM t WHERE inside AND y BETWEEN 1940 AND 1965").fetchone()[0]
    heritage["summary"] = {**strict, "postwar_buildings_inside": int(postwar_inside),
                           "postwar_buildings_inside_listed_pct": round(100 * strict["inside_postwar"] / postwar_inside, 1)}
    m_out = m[m["inside"]].sort_values(["period", "bouwjaar"])[["monument_nr", "name", "bouwjaar", "period", "designated", "ciCitation", "dist_m"]]
    m_out.to_csv(DATA / "monuments.csv", index=False)

    st = json.loads((DATA / "stats.json").read_text())
    st["analysis"] = {"robustness": robust, "heritage": heritage,
                      "sources": {"monuments": "RCE rijksmonumenten (INSPIRE protected sites, points) via PDOK WFS ps-ch, CC BY 4.0"}}
    (DATA / "stats.json").write_text(json.dumps(st, indent=1, ensure_ascii=False))
    print(json.dumps(st["analysis"], indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
