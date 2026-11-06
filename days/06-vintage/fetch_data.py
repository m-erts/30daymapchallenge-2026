"""Day 6 (Vintage): download the open data behind the Rotterdam 1940 map.

    python fetch_data.py            # ~60 WFS + ~20 API requests, 2-4 min

- BAG panden (buildings with bouwjaar) from the PDOK WFS: public domain (PDOK page: Public Domain
  Mark 1.0; WFS capabilities: CC0 1.0). Source holders: Kadaster and the municipalities.
- BGT waterdelen (water surfaces) from the PDOK OGC API, CC0 1.0. The API also returns ended
  (historical) versions; make_map.py keeps only those without eind_registratie.
- Brandgrens lights from Gemeente Rotterdam's public-lighting WFS (layer ms:sdo_gwr_bsb_ovl,
  ARMATUURTYPE = 'Grondspot Medio type Brandgrens'); Nationaal Georegister record
  918e4b3a-6af8-452e-a1fb-6b2f044b3246: "geen beperkingen", Public Domain Mark 1.0. Latin-1 encoded.

All go to data/raw/ (git-ignored) together with a small JSON note of when they were downloaded
(local time).
The bounding box is generous around the 1940 fire zone; make_map.py crops it.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "raw"
# RD New (EPSG:28992): the inner city of Rotterdam, Noordereiland, Kralingen-West, Kop van Zuid
BBOX = (89500, 434500, 96000, 439500)
TILE = 500
VBO_BBOX = (91000, 435500, 95500, 439000)   # addresses only for the interactive map
BAG_WFS = "https://service.pdok.nl/lv/bag/wfs/v2_0"
BGT_API = "https://api.pdok.nl/lv/bgt/ogc/v1/collections/waterdeel/items"
RD = "http://www.opengis.net/def/crs/EPSG/0/28992"
LIGHTS_WFS = r"https://ows.gis.rotterdam.nl/cgi-bin/mapserv.exe?map=d:\gwr\webdata\mapserver\map\bbdwh_pub.map"
LIGHTS_FILTER = ('<Filter xmlns="http://www.opengis.net/fes/2.0"><PropertyIsEqualTo><ValueReference>ARMATUURTYPE'
                 '</ValueReference><Literal>Grondspot Medio type Brandgrens</Literal></PropertyIsEqualTo></Filter>')
UA = {"User-Agent": "30DayMapChallenge-2026 day 6 (research; contact via github.com/m-erts)"}


def get(url, params, tries=4):
    for k in range(tries):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=120)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 - retry any network or JSON error
            if k == tries - 1:
                raise
            print(f"  retry {k + 1}: {e}")
            time.sleep(3 * (k + 1))


def fetch_bag():
    out = RAW / "bag_pand.gpkg"
    if out.exists():
        print("BAG already there:", out)
        return
    feats, seen = [], set()
    x0, y0, x1, y1 = BBOX
    tiles = [(x, y) for x in range(x0, x1, TILE) for y in range(y0, y1, TILE)]
    for n, (x, y) in enumerate(tiles, 1):
        start = 0
        while True:
            d = get(BAG_WFS, {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                              "typeNames": "bag:pand", "outputFormat": "application/json",
                              "srsName": "EPSG:28992", "count": 1000, "startIndex": start,
                              "bbox": f"{x},{y},{x + TILE},{y + TILE},urn:ogc:def:crs:EPSG::28992"})
            fs = d.get("features", [])
            for f in fs:
                pid = f["properties"]["identificatie"]
                if pid not in seen:
                    seen.add(pid)
                    feats.append(f)
            if len(fs) < 1000:
                break
            start += 1000
        if n % 20 == 0:
            print(f"  BAG tile {n}/{len(tiles)}: {len(feats)} buildings")
    gdf = gpd.GeoDataFrame.from_features(feats, crs=28992)
    gdf = gdf[["identificatie", "bouwjaar", "status", "gebruiksdoel", "oppervlakte_max",
               "aantal_verblijfsobjecten", "geometry"]]
    gdf.to_file(out, driver="GPKG")
    print(f"BAG: {len(gdf)} buildings -> {out}")


def fetch_addresses():
    """BAG verblijfsobjecten (addresses) for the area of the interactive map, to label buildings."""
    out = RAW / "bag_vbo.gpkg"
    if out.exists():
        print("BAG addresses already there:", out)
        return
    feats, seen = [], set()
    x0, y0, x1, y1 = VBO_BBOX
    tiles = [(x, y) for x in range(x0, x1, TILE) for y in range(y0, y1, TILE)]
    for n, (x, y) in enumerate(tiles, 1):
        start = 0
        while True:
            d = get(BAG_WFS, {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                              "typeNames": "bag:verblijfsobject", "outputFormat": "application/json",
                              "srsName": "EPSG:28992", "count": 1000, "startIndex": start,
                              "bbox": f"{x},{y},{x + TILE},{y + TILE},urn:ogc:def:crs:EPSG::28992"})
            fs = d.get("features", [])
            for f in fs:
                vid = f["properties"]["identificatie"]
                if vid not in seen:
                    seen.add(vid)
                    feats.append(f)
            if len(fs) < 1000:
                break
            start += 1000
        if n % 20 == 0:
            print(f"  addresses tile {n}/{len(tiles)}: {len(feats)}")
    gdf = gpd.GeoDataFrame.from_features(feats, crs=28992)
    keep = ["identificatie", "openbare_ruimte", "huisnummer", "huisletter", "toevoeging", "postcode",
            "gebruiksdoel", "pandidentificatie", "status", "geometry"]
    gdf[[c for c in keep if c in gdf.columns]].to_file(out, driver="GPKG")
    print(f"BAG addresses: {len(gdf)} -> {out}")


WD_QUERY = """
SELECT DISTINCT ?item ?label_en ?label_nl ?coord ?inception ?end ?inst_nl ?nlwiki ?enwiki WHERE {
  SERVICE wikibase:box {
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point(4.44 51.90)"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerNorthEast "Point(4.53 51.945)"^^geo:wktLiteral .
  }
  ?item wdt:P576 ?end . FILTER(YEAR(?end) = 1940)
  OPTIONAL { ?item wdt:P571 ?inception . }
  OPTIONAL { ?item wdt:P31 ?inst . ?inst rdfs:label ?inst_nl . FILTER(LANG(?inst_nl) = "nl") }
  OPTIONAL { ?item rdfs:label ?label_en . FILTER(LANG(?label_en) = "en") }
  OPTIONAL { ?item rdfs:label ?label_nl . FILTER(LANG(?label_nl) = "nl") }
  OPTIONAL { ?nlwiki schema:about ?item ; schema:isPartOf <https://nl.wikipedia.org/> . }
  OPTIONAL { ?enwiki schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }
}"""


def fetch_wikidata():
    """Wikidata items with coordinates in central Rotterdam whose 'dissolved, abolished or demolished
    date' (P576) falls in 1940: buildings lost in the bombing, plus streets and bridges (filtered later)."""
    out = RAW / "wikidata_ended_1940.json"
    if out.exists():
        print("Wikidata already there:", out)
        return
    r = requests.get("https://query.wikidata.org/sparql", params={"query": WD_QUERY},
                     headers={**UA, "Accept": "application/sparql-results+json"}, timeout=120)
    r.raise_for_status()
    out.write_bytes(r.content)
    print(f"Wikidata: {len(r.json()['results']['bindings'])} rows -> {out}")


def fetch_water():
    out = RAW / "bgt_waterdeel.gpkg"
    if out.exists():
        print("BGT water already there:", out)
        return
    params = {"bbox": ",".join(map(str, BBOX)), "bbox-crs": RD, "crs": RD, "limit": 1000, "f": "json"}
    url, feats = BGT_API, []
    while url:
        d = get(url, params)
        feats += d.get("features", [])
        url = next((l["href"] for l in d.get("links", []) if l.get("rel") == "next"), None)
        params = None  # the next link carries all parameters
    gdf = gpd.GeoDataFrame.from_features(feats, crs=28992)
    keep = [c for c in ("lokaal_id", "type", "plus_type", "eind_registratie") if c in gdf.columns]
    gdf[keep + ["geometry"]].to_file(out, driver="GPKG")
    print(f"BGT water: {len(gdf)} parts -> {out}")


def fetch_lights():
    out = RAW / "lights" / "brandgrens_lights.geojson"
    if out.exists():
        print("lights already there:", out)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    r = requests.get(LIGHTS_WFS, params={"service": "WFS", "version": "2.0.0", "request": "GetFeature",
                                         "typeNames": "ms:sdo_gwr_bsb_ovl", "outputFormat": "geojson",
                                         "srsName": "EPSG:28992", "FILTER": LIGHTS_FILTER}, headers=UA, timeout=120)
    r.raise_for_status()
    out.write_bytes(r.content)
    print(f"lights: {len(json.loads(r.content.decode('latin-1'))['features'])} -> {out}")


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    fetch_bag()
    fetch_water()
    fetch_lights()
    fetch_addresses()
    fetch_wikidata()
    note = RAW / "downloaded.json"
    meta = json.loads(note.read_text()) if note.exists() else {}
    for name in ("bag_pand.gpkg", "bgt_waterdeel.gpkg", "lights/brandgrens_lights.geojson", "bag_vbo.gpkg",
                 "wikidata_ended_1940.json"):
        f = RAW / name
        if f.exists():
            meta.setdefault(name, datetime.fromtimestamp(f.stat().st_mtime, timezone.utc).astimezone()
                            .strftime("%Y-%m-%d %H:%M %Z"))
    note.write_text(json.dumps(meta, indent=1))
    print(meta)


if __name__ == "__main__":
    main()
