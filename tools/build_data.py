"""Regenerate the bundled reference data in ``dwdpheno/data/`` (developer tool, stdlib only).

Sources
  * Administrative boundaries: BKG VG2500, Datenlizenz Deutschland - Namensnennung - 2.0
      https://daten.gdz.bkg.bund.de/produkte/vg/vg2500/aktuell/
      Required source note (BKG terms of use for VG2500), with the year of download:
        (c) BKG (<year>) dl-de/by-2-0 (Daten veraendert), Datenquellen:
        https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/datenquellen_vg_nuts.pdf
  * Places: GeoNames DE dump, CC BY 4.0 (https://www.geonames.org/)
      https://download.geonames.org/export/dump/DE.zip
  Changes made: reprojected UTM32 -> WGS84 and rounded to 5 decimals, land areas only, English
  region types added; places filtered (population >= MIN_POP) and assigned to Bundeslaender.
  See THIRD_PARTY_NOTICES.md.

Outputs in dwdpheno/data/ (all UTF-8, lon/lat WGS84), shipped as package data
  states.geojson     16 Bundeslaender            (map overlay)
  counties.geojson   401 Kreise / kreisfreie Staedte (map overlay)
  regions.txt        the same polygons in a line format any language can read
  Region types are English ("type", e.g. "rural district") with the German BKG term in "type_de".
  cities.txt         populated places >= MIN_POP:  name;lat;lon;population;state

Usage:  python tools/build_data.py [workdir]
"""
from __future__ import annotations

import io
import json
import math
import sqlite3
import struct
import sys
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

VG_URL = 'https://daten.gdz.bkg.bund.de/produkte/vg/vg2500/aktuell/vg2500_01-01-2026.utm32s.gpkg.zip'
GN_URL = 'https://download.geonames.org/export/dump/DE.zip'
MIN_POP = 1000
OUT = Path(__file__).resolve().parents[1] / 'dwdpheno' / 'data'
UA = {'User-Agent': 'dwdpheno-build-data'}

# BKG region type (BEZ) -> English
TYPE_EN = {'Landkreis': 'rural district', 'Kreis': 'district', 'Kreisfreie Stadt': 'urban district',
           'Stadtkreis': 'urban district', 'Land': 'state', 'Freistaat': 'free state',
           'Freie und Hansestadt': 'free Hanseatic city', 'Freie Hansestadt': 'free Hanseatic city'}

# GeoNames admin1 code -> Bundesland
ADMIN1 = {'01': 'Baden-Württemberg', '02': 'Bayern', '16': 'Berlin', '11': 'Brandenburg',
          '03': 'Bremen', '04': 'Hamburg', '05': 'Hessen', '12': 'Mecklenburg-Vorpommern',
          '06': 'Niedersachsen', '07': 'Nordrhein-Westfalen', '08': 'Rheinland-Pfalz',
          '09': 'Saarland', '13': 'Sachsen', '14': 'Sachsen-Anhalt', '10': 'Schleswig-Holstein',
          '15': 'Thüringen'}


def fetch(url: str, work: Path) -> bytes:
    f = work / url.rsplit('/', 1)[-1]
    if not f.exists():
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r:
            f.write_bytes(r.read())
    return f.read_bytes()


def utm32_to_wgs84(e: float, n: float) -> tuple[float, float]:
    """Inverse transverse Mercator, ETRS89/GRS80 zone 32N (Snyder 1987, eq. 8-18..8-25)."""
    a, f, k0 = 6378137.0, 1 / 298.257222101, 0.9996
    e2 = f * (2 - f); ep2 = e2 / (1 - e2)
    x, y = e - 500000.0, n
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    p1 = (mu + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
          + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
          + (151 * e1**3 / 96) * math.sin(6 * mu) + (1097 * e1**4 / 512) * math.sin(8 * mu))
    c1 = ep2 * math.cos(p1)**2; t1 = math.tan(p1)**2
    n1 = a / math.sqrt(1 - e2 * math.sin(p1)**2)
    r1 = a * (1 - e2) / (1 - e2 * math.sin(p1)**2)**1.5
    d = x / (n1 * k0)
    lat = p1 - (n1 * math.tan(p1) / r1) * (d**2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
                                           + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ep2 - 3 * c1**2) * d**6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d**3 / 6
           + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120) / math.cos(p1)
    return round(9.0 + math.degrees(lon), 5), round(math.degrees(lat), 5)


def gpkg_polygons(blob: bytes) -> list[list[list[tuple[float, float]]]]:
    """GeoPackage geometry blob -> list of polygons, each a list of rings (lon, lat)."""
    flags = blob[3]
    env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
    buf = memoryview(blob)[8 + env:]
    pos = 0

    def geom():
        nonlocal pos
        bo = '<' if buf[pos] == 1 else '>'
        typ, = struct.unpack_from(bo + 'I', buf, pos + 1); pos += 5
        typ %= 1000
        if typ == 3:
            nr, = struct.unpack_from(bo + 'I', buf, pos); pos += 4
            rings = []
            for _ in range(nr):
                npt, = struct.unpack_from(bo + 'I', buf, pos); pos += 4
                pts = struct.unpack_from(bo + f'{2 * npt}d', buf, pos); pos += 16 * npt
                rings.append([utm32_to_wgs84(pts[i], pts[i + 1]) for i in range(0, 2 * npt, 2)])
            return [rings]
        if typ == 6:
            n, = struct.unpack_from(bo + 'I', buf, pos); pos += 4
            return [p for _ in range(n) for p in geom()]
        raise ValueError(f'unsupported WKB type {typ}')
    return geom()


def main(work: Path) -> None:
    work.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(fetch(VG_URL, work))) as z:
        name = next(n for n in z.namelist() if n.endswith('.gpkg'))
        (work / 'vg2500.gpkg').write_bytes(z.read(name))
    db = sqlite3.connect(work / 'vg2500.gpkg')
    state_of = {sn: gen for sn, gen in db.execute('select SN_L, GEN from vg2500_lan where GF=9')}

    layers = {
        'S': [(f'DE-{sn}', gen, bez, gen, gpkg_polygons(g))
              for sn, gen, bez, g in db.execute('select SN_L, GEN, BEZ, geom from vg2500_lan where GF=9 order by SN_L')],
        'C': [(ags, gen, bez, state_of[sn], gpkg_polygons(g))
              for ags, gen, bez, sn, g in db.execute('select AGS, GEN, BEZ, SN_L, geom from vg2500_krs where GF=9 order by AGS')],
    }

    for kind, fname in (('S', 'states.geojson'), ('C', 'counties.geojson')):
        feats = [{'type': 'Feature',
                  'properties': {'id': code, 'name': gen, 'type': TYPE_EN[bez], 'type_de': bez,
                                 'state': st},
                  'geometry': {'type': 'MultiPolygon', 'coordinates': [[[list(p) for p in r] for r in poly] for poly in polys]}}
                 for code, gen, bez, st, polys in layers[kind]]
        (OUT / fname).write_text(json.dumps({'type': 'FeatureCollection', 'features': feats},
                                            ensure_ascii=False, separators=(',', ':')), encoding='utf-8')

    # Line format: header, then per region "R kind code nrings name|type|state", per ring "npts", then "lon lat" lines.
    lines = [f'# DWDPheno regions v2 - VG2500 (c) BKG ({date.today().year}) dl-de/by-2-0 (Daten veraendert),'
             ' Datenquellen: https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/datenquellen_vg_nuts.pdf;'
             ' lon lat WGS84; R <S|C> <code> <nrings> <name>|<type>|<state>|<type_de>']
    for kind in ('S', 'C'):
        for code, gen, bez, st, polys in layers[kind]:
            rings = [r for poly in polys for r in poly]
            lines.append(f'R {kind} {code} {len(rings)} {gen}|{TYPE_EN[bez]}|{st}|{bez}')
            for r in rings:
                lines.append(str(len(r)))
                lines.extend(f'{lon:.5f} {lat:.5f}' for lon, lat in r)
    (OUT / 'regions.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')

    with zipfile.ZipFile(io.BytesIO(fetch(GN_URL, work))) as z:
        rows = z.read('DE.txt').decode('utf-8').splitlines()
    cities = {}
    for r in rows:
        c = r.split('\t')
        if c[6] != 'P' or not c[14].isdigit() or int(c[14]) < MIN_POP or c[7] in ('PPLH', 'PPLQ', 'PPLW', 'PPLX'):
            continue
        key = (c[1], ADMIN1.get(c[10], ''))
        if key not in cities or int(c[14]) > cities[key][2]:
            cities[key] = (float(c[4]), float(c[5]), int(c[14]))
    out = ['# name;lat;lon;population;state - GeoNames (https://www.geonames.org/), CC BY 4.0;'
           f' modified: places with population >= {MIN_POP}, state names added']
    for (nm, st), (lat, lon, pop) in sorted(cities.items(), key=lambda kv: -kv[1][2]):
        out.append(f'{nm};{lat:.5f};{lon:.5f};{pop};{st}')
    (OUT / 'cities.txt').write_text('\n'.join(out) + '\n', encoding='utf-8')
    print(f"{len(layers['S'])} states, {len(layers['C'])} counties, {len(out) - 1} places -> {OUT}")


if __name__ == '__main__':
    main(Path(sys.argv[1] if len(sys.argv) > 1 else Path.home() / '.cache' / 'dwdpheno-build'))
