"""Day 6: the 1940 fire boundary (brandgrens) from the city's own street lights.

Since 2010 the brandgrens is marked in the pavement with lights (design West 8 with Opera Graphic
Design): red on the mainland, green on the Noordereiland. Gemeente Rotterdam publishes its public
lighting as a WFS (Nationaal Georegister: "geen beperkingen", Public Domain Mark 1.0); the lights of
type "Grondspot Medio type Brandgrens" are the line. This script

1. keeps the lights numbered "1940..." / "1941..." (4 lights in Schietbaanstraat, numbered 056-064,
   lie 500 m off the line and are left out);
2. joins neighbouring lights of one colour into a minimum spanning tree (edges <= 160 m) = the
   line as drawn on the map, with its gaps where no lights are registered;
3. closes the zone for counting: three bridges over gaps without lights (station area, Admiraliteitskade,
   Plantage-oost) and a closing line through the Nieuwe Maas, so the harbours and quays inside count
   as inside; on the Noordereiland two pieces, each closed through the river on the NW side;
4. writes data/brandgrens_lights.geojson (points), data/brandgrens_line.geojson (MST edges) and
   data/brandgrens_zone.geojson (polygons used for counting).

    python build_brandgrens.py
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point
from shapely.ops import polygonize, unary_union

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
DATA = HERE / "data"
LIGHTS = RAW / "lights" / "brandgrens_lights.geojson"
MAX_EDGE = 160.0

# Light ids (index after filtering) are not stable between downloads, so bridges are given by
# coordinates and snapped to the nearest light.
BRIDGES = [  # (from, to) in RD; straight segments where the street has no registered lights
    ((91986, 437701), (92360, 437896)),    # Weena / station area
    ((93881, 437334), (94128, 437382)),    # Oostplein -> Admiraliteitskade
    ((94236, 437463), (94312, 437654)),    # east of the Plantage
]
# closing line through the Nieuwe Maas, from the east end (Buizengat) to the west end (Westerkade)
RIVER_MAIN = [(94432, 437075), (94440, 436990), (94200, 436960), (93900, 436900), (93600, 436760),
              (93350, 436560), (93120, 436330), (92930, 436130), (92790, 435960), (92699, 435944)]
# Noordereiland: west tip (lights cross the island) and the north-east quay
RIVER_NDL_W = [(93311, 436312), (93200, 436330), (93060, 436120), (93120, 436040), (93297, 436096)]
RIVER_NDL_E = [(93778, 436743), (93760, 436800), (94000, 436880), (94200, 436850), (94180, 436760),
               (94055, 436718)]
# one point inside each zone, used to pick the polygons that polygonize returns
SEEDS = {"centre": (92969, 437393), "noordereiland_west": (93200, 436150),
         "noordereiland_east": (94000, 436790)}


def load_lights():
    d = json.loads(LIGHTS.read_text(encoding="latin-1"))
    g = gpd.GeoDataFrame.from_features(d["features"], crs=28992)
    g = g[g["LICHTPUNTNUMMER"].astype(str).str.startswith("194")].reset_index(drop=True)
    g["colour"] = np.where(g["LICHTBRONKLEUR"].eq("groen"), "green", "red")
    return g[["LICHTPUNT_ID", "LICHTPUNTNUMMER", "STRAAT", "WIJK", "colour", "PLAATSINGSDATUM_ARMATUUR", "geometry"]]


def mst_edges(g):
    xy = np.c_[g.geometry.x, g.geometry.y]
    G = nx.Graph()
    G.add_nodes_from(range(len(xy)))
    for i, j in cKDTree(xy).query_pairs(MAX_EDGE):
        if g.colour.iat[i] == g.colour.iat[j]:
            G.add_edge(i, j, weight=float(np.hypot(*(xy[i] - xy[j]))))
    T = nx.minimum_spanning_tree(G)
    return [LineString([xy[i], xy[j]]) for i, j in T.edges()], [g.colour.iat[i] for i, j in T.edges()]


def snap(pt, xy):
    return tuple(xy[np.argmin(np.hypot(*(xy - np.array(pt)).T))])


def build():
    g = load_lights()
    xy = np.c_[g.geometry.x, g.geometry.y]
    edges, colours = mst_edges(g)
    line = gpd.GeoDataFrame({"colour": colours}, geometry=edges, crs=28992)
    closing = [LineString([snap(a, xy), snap(b, xy)]) for a, b in BRIDGES]
    for path in (RIVER_MAIN, RIVER_NDL_W, RIVER_NDL_E):
        pts = [snap(path[0], xy)] + list(path[1:-1]) + [snap(path[-1], xy)]
        closing.append(LineString(pts))
    faces = list(polygonize(unary_union(edges + closing)))
    zones = []
    for name, s in SEEDS.items():
        hit = [f for f in faces if f.contains(Point(s))]
        if not hit:
            raise SystemExit(f"no closed face around seed {name}: check bridges / river lines")
        zones.append({"zone": name, "geometry": hit[0]})
    zone = gpd.GeoDataFrame(zones, crs=28992)
    zone["area_ha"] = (zone.area / 1e4).round(1)
    DATA.mkdir(exist_ok=True)
    g.to_file(DATA / "brandgrens_lights.geojson", driver="GeoJSON")
    line.to_file(DATA / "brandgrens_line.geojson", driver="GeoJSON")
    zone.to_file(DATA / "brandgrens_zone.geojson", driver="GeoJSON")
    bridges = gpd.GeoDataFrame(geometry=closing, crs=28992)
    bridges.to_file(DATA / "brandgrens_closing.geojson", driver="GeoJSON")
    print(f"{len(g)} lights ({(g.colour == 'green').sum()} green), {len(line)} line segments,"
          f" line length {line.length.sum() / 1000:.1f} km")
    print(zone[["zone", "area_ha"]].to_string(index=False))
    return g, line, zone, bridges


if __name__ == "__main__":
    build()
