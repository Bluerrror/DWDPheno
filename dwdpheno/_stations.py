"""Station metadata, county / nearest-place enrichment and station selection."""
from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import _http
from ._text import any_match, as_list, fold
from ._catalog import HELP_URL, REPORTERS, read_table

STATION_COLUMNS = ["station_id", "station_name", "latitude", "longitude", "elevation_m", "state",
                   "county", "county_type", "county_id", "nearest_place", "nearest_place_km",
                   "naturraumgruppe", "naturraum", "active_until", "reporter"]
PLACE_COLUMNS = ["name", "latitude", "longitude", "population", "state"]
SELECTION_KEYS = ("station_id", "name", "state", "county", "city", "lat", "lon", "radius_km",
                  "nearest", "bbox", "polygon", "reporter", "active")
EARTH_RADIUS_KM = 6371.0
DEFAULT_RADIUS_KM = 25.0


# ---------------------------------------------------------------------------------------------
#  Reference data (BKG VG2500 counties, GeoNames places)
# ---------------------------------------------------------------------------------------------

def data_dir() -> Path:
    """``$DWDPHENO_DATA`` or the ``data`` folder shipped inside the package."""
    env = os.environ.get("DWDPHENO_DATA")
    return Path(env) if env else Path(__file__).resolve().parent / "data"


@functools.lru_cache(maxsize=2)
def _regions(path: str, kind: str = "C"):
    """Parse ``regions.txt`` → list of ``(code, name, type, state, type_de, bbox, rings)``.

    Header lines read ``R <S|C> <code> <nrings> <name>|<type>|<state>|<type_de>``; rings are
    (lon, lat) arrays.
    """
    out = []
    with open(path, encoding="utf-8") as fh:
        it = iter(fh)
        for line in it:
            if not line.startswith("R "):
                continue
            _, k, code, nrings, rest = line.rstrip("\n").split(" ", 4)
            name, typ, state, typ_de = (rest.split("|") + ["", "", ""])[:4]
            rings = []
            for _ in range(int(nrings)):
                npts = int(next(it))
                rings.append(np.array([next(it).split() for _ in range(npts)], dtype=float))
            if k != kind:
                continue
            allp = np.vstack(rings)
            bbox = (allp[:, 0].min(), allp[:, 1].min(), allp[:, 0].max(), allp[:, 1].max())
            out.append((code, name, typ, state, typ_de or typ, bbox, rings))
    return out


def _even_odd(px: np.ndarray, py: np.ndarray, rings: Sequence[np.ndarray]) -> np.ndarray:
    """Even-odd point-in-polygon for points ``(px, py)`` against all ``rings`` of one region."""
    inside = np.zeros(px.shape, dtype=bool)
    for ring in rings:
        x1, y1 = ring[:, 0][:, None], ring[:, 1][:, None]
        x2, y2 = np.roll(ring[:, 0], -1)[:, None], np.roll(ring[:, 1], -1)[:, None]
        straddle = (y1 > py) != (y2 > py)
        with np.errstate(divide="ignore", invalid="ignore"):
            xcross = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
        inside ^= (np.count_nonzero(straddle & (px < xcross), axis=0) % 2).astype(bool)
    return inside


def assign_counties(lat, lon) -> pd.DataFrame:
    """County (``county``, English ``county_type``, ``county_id``) for each point; missing
    outside Germany."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    n = lat.size
    idx = np.full(n, -1)
    regs = _regions(str(data_dir() / "regions.txt"))
    for i, (_, _, _, _, _, (x0, y0, x1, y1), rings) in enumerate(regs):
        cand = np.flatnonzero((idx < 0) & (lon >= x0) & (lon <= x1) & (lat >= y0) & (lat <= y1))
        if cand.size:
            hit = _even_odd(lon[cand], lat[cand], rings)
            idx[cand[hit]] = i
    pick = lambda j: [regs[k][j] if k >= 0 else None for k in idx]  # noqa: E731
    return pd.DataFrame({"county": pick(1), "county_type": pick(2), "county_id": pick(0)},
                        dtype=object)


def _county_type_de() -> dict:
    """county_id → German county type (``Landkreis``, ``Kreisfreie Stadt``, ...)."""
    return {r[0]: r[4] for r in _regions(str(data_dir() / "regions.txt"))}


@functools.lru_cache(maxsize=2)
def _places(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, sep=";", comment="#", header=None, names=PLACE_COLUMNS,
                     encoding="utf-8", keep_default_na=False)
    df["population"] = df["population"].astype("int64")
    df["_fold"] = df["name"].map(fold)
    return df


def _place_table() -> pd.DataFrame:
    return _places(str(data_dir() / "cities.txt"))


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = (np.sin((p2 - p1) / 2) ** 2 +
         np.cos(p1) * np.cos(p2) * np.sin(np.radians(np.asarray(lon2) - np.asarray(lon1)) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def nearest_places(lat, lon, chunk: int = 512) -> pd.DataFrame:
    """Nearest entry of the bundled place list (``nearest_place, nearest_place_km``) for each point."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    pl = _place_table()
    plat, plon = pl["latitude"].to_numpy(float), pl["longitude"].to_numpy(float)
    names = pl["name"].to_numpy(object)
    best_i = np.zeros(lat.size, dtype=int)
    best_d = np.full(lat.size, np.nan)
    for s in range(0, lat.size, chunk):
        d = haversine_km(lat[s:s + chunk, None], lon[s:s + chunk, None], plat[None, :], plon[None, :])
        d = np.where(np.isnan(d), np.inf, d)
        best_i[s:s + chunk] = d.argmin(axis=1)
        best_d[s:s + chunk] = d.min(axis=1)
    ok = np.isfinite(best_d)
    return pd.DataFrame({"nearest_place": np.where(ok, names[best_i], None),
                         "nearest_place_km": np.where(ok, np.round(best_d, 2), np.nan)})


def places(q: Optional[str] = None, limit: Optional[int] = None) -> pd.DataFrame:
    """Search the bundled German place list (GeoNames, population >= 1000).

    Exact (folded) name matches first, then by population.  Columns
    ``name, latitude, longitude, population, state``.
    """
    df = _place_table()
    if q:
        fq = fold(q)
        toks = fq.split()
        hit = df["_fold"].map(lambda t: all(tok in t for tok in toks)).astype(bool)
        df = df[hit].assign(_exact=(df["_fold"][hit] != fq))
        df = df.sort_values(["_exact", "population"], ascending=[True, False], kind="stable")
    out = df[PLACE_COLUMNS].reset_index(drop=True)
    return out.head(limit) if limit else out


# ---------------------------------------------------------------------------------------------
#  Station table
# ---------------------------------------------------------------------------------------------

_STATION_RENAME = {"Stations_id": "station_id", "Stationsname": "station_name",
                   "geograph.Breite": "latitude", "geograph.Laenge": "longitude",
                   "Stationshoehe": "elevation_m", "Naturraumgruppe": "naturraumgruppe",
                   "Naturraum": "naturraum", "Datum Stationsaufloesung": "active_until",
                   "Bundesland": "state"}


def parse_stations(raw: bytes) -> pd.DataFrame:
    """Parse a ``PH_Beschreibung_Phaenologie_Stationen_*.txt`` file."""
    df = read_table(raw).rename(columns=_STATION_RENAME)
    df["station_id"] = pd.to_numeric(df["station_id"], errors="coerce")
    df = df.dropna(subset=["station_id"])
    df["station_id"] = df["station_id"].astype("int64")
    for c in ("latitude", "longitude"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64").round(4)
    df["elevation_m"] = pd.to_numeric(df["elevation_m"], errors="coerce").round().astype("Int64")
    return df


def station_url(reporter: str) -> str:
    return f"{HELP_URL}/PH_Beschreibung_Phaenologie_Stationen_{REPORTERS[reporter][1]}.txt"


@functools.lru_cache(maxsize=4)
def _build_table(raws: Tuple[Tuple[str, bytes], ...]) -> pd.DataFrame:
    frames = []
    for rep, raw in raws:
        frames.append(parse_stations(raw).assign(_rep=rep))
    df = pd.concat(frames, ignore_index=True)
    reps = df.groupby("station_id")["_rep"].agg(lambda s: s.iloc[0] if s.nunique() == 1 else "both")
    df = df.drop_duplicates("station_id", keep="first").reset_index(drop=True)
    df["reporter"] = df["station_id"].map(reps)
    df = pd.concat([df, assign_counties(df["latitude"], df["longitude"]),
                    nearest_places(df["latitude"], df["longitude"])], axis=1)
    for c in STATION_COLUMNS:
        if c not in df.columns:
            df[c] = None
    df = df[STATION_COLUMNS].sort_values("station_id").reset_index(drop=True)
    for c in ("station_name", "state", "county", "county_type", "county_id", "nearest_place",
              "naturraumgruppe", "naturraum", "active_until", "reporter"):
        df[c] = df[c].astype("string")
    return df


def station_table(*, reporter: str = "both", cache=None, offline: bool = False,
                  max_age_days: float = 1.0) -> pd.DataFrame:
    """The full, enriched station table (union of annual + immediate station files)."""
    reps = ("annual", "immediate") if reporter == "both" else (reporter,)
    raws = []
    for rep in reps:
        try:
            raws.append((rep, _http.fetch(station_url(rep), cache=cache, offline=offline,
                                          max_age_days=max_age_days)))
        except _http.NetworkError:
            if len(reps) == 1:
                raise
    if not raws:
        raise _http.NetworkError("could not load any DWD station metadata file")
    return _build_table(tuple(raws)).copy()


def _ids(value) -> Optional[List[int]]:
    vals = as_list(value)
    return None if vals is None else [int(v) for v in vals]


def _pair(value, n: int, what: str) -> List[float]:
    vals = [float(v) for v in (as_list(value) or [])]
    if len(vals) != n:
        raise ValueError(f"{what} needs {n} numbers, got {value!r}")
    return vals


def _polygon(value) -> List[Tuple[float, float]]:
    if isinstance(value, str):
        pts = [p.replace(",", " ").split() for p in value.split(";") if p.strip()]
        value = [(float(a), float(b)) for a, b in pts]
    pts = [(float(a), float(b)) for a, b in value]
    if len(pts) < 3:
        raise ValueError("polygon needs at least 3 (lat, lon) vertices")
    return pts


def resolve_city(city: str) -> pd.Series:
    """Best-matching place for ``city`` (exact folded name first, then largest population)."""
    hits = places(city)
    if hits.empty:
        raise _http.NoMatchError(f"no place matches {city!r}")
    return hits.iloc[0]


def select_stations(table: pd.DataFrame, *, station_id=None, name=None, state=None, county=None,
                    city: Optional[str] = None, lat: Optional[float] = None,
                    lon: Optional[float] = None, radius_km: Optional[float] = None,
                    nearest: Optional[int] = None, bbox=None, polygon=None,
                    reporter: str = "both", active: bool = False) -> pd.DataFrame:
    """Apply a station selection (all given criteria AND-ed) to a station table.

    ``name``/``state``/``county`` accept a string (comma = OR) or a list; ``county`` is matched
    against ``"{county} {county_type} {county_type_de}"`` (``"Kassel rural district"`` or
    ``"Landkreis Kassel"``).  A centre (``city`` or ``lat``+``lon``) adds
    ``distance_km`` and keeps stations within ``radius_km`` (default 25) or the ``nearest`` k.
    """
    df = table
    m = pd.Series(True, index=df.index)
    ids = _ids(station_id)
    if ids is not None:
        m &= df["station_id"].isin(ids)
    for col, val in (("station_name", name), ("state", state)):
        qs = as_list(val)
        if qs:
            m &= df[col].map(lambda t, qs=qs: any_match(qs, t)).astype(bool)
    qs = as_list(county)
    if qs:
        type_de = df["county_id"].map(_county_type_de()).fillna("")
        text = df["county"].fillna("") + " " + df["county_type"].fillna("") + " " + type_de
        m &= text.map(lambda t: any_match(qs, t)).astype(bool) & df["county"].notna()
    if reporter not in ("both", "annual", "immediate"):
        raise ValueError(f"reporter must be 'annual', 'immediate' or 'both', got {reporter!r}")
    if reporter != "both":
        m &= df["reporter"].isin([reporter, "both"])
    if active:
        m &= df["active_until"].isna()
    if bbox is not None:
        s, w, n, e = _pair(bbox, 4, "bbox (s, w, n, e)")
        m &= df["latitude"].between(s, n) & df["longitude"].between(w, e)
    if polygon is not None:
        pts = np.array(_polygon(polygon))
        ring = np.vstack([pts[:, 1], pts[:, 0]]).T  # (lon, lat)
        m &= pd.Series(_even_odd(df["longitude"].to_numpy(float), df["latitude"].to_numpy(float),
                                 [ring]), index=df.index)
    df = df[m]

    if city is not None:
        place = resolve_city(city)
        lat, lon = float(place["latitude"]), float(place["longitude"])
    if (lat is None) != (lon is None):
        raise ValueError("lat and lon must be given together")
    if lat is None:
        if radius_km is not None or nearest is not None:
            raise ValueError("radius_km / nearest need a centre (city= or lat= and lon=)")
        return df.sort_values("station_id", kind="stable").reset_index(drop=True)

    dist = haversine_km(float(lat), float(lon), df["latitude"].to_numpy(float),
                        df["longitude"].to_numpy(float))
    df = df.assign(distance_km=np.round(dist, 2), _d=dist)
    df = df.sort_values(["_d", "station_id"], kind="stable")
    if nearest is not None:
        df = df.head(int(nearest))
    else:
        r = DEFAULT_RADIUS_KM if radius_km is None else float(radius_km)
        df = df[df["_d"] <= r]
    return df.drop(columns="_d").reset_index(drop=True)


def stations(*, station_id=None, name=None, state=None, county=None, city: Optional[str] = None,
             lat: Optional[float] = None, lon: Optional[float] = None,
             radius_km: Optional[float] = None, nearest: Optional[int] = None, bbox=None,
             polygon=None, reporter: str = "both", active: bool = False, crops=None,
             years=None, partition: str = "both", quality=None, quality_level=None, cache=None,
             offline: bool = False, max_age_days: float = 1.0, verbose: bool = False,
             progress=None) -> pd.DataFrame:
    """DWD phenology stations, enriched with county and nearest place, filtered by a selection.

    Selection keywords: ``station_id, name, state, county, city, lat, lon, radius_km, nearest,
    bbox=(s, w, n, e), polygon=[(lat, lon), ...], reporter, active`` (all AND-ed).

    With ``crops`` only the selected stations that have observations of those crops are returned
    (after ``years``, ``partition``, ``reporter``, ``quality`` / ``quality_level`` and the
    historical/recent de-duplication, exactly as :func:`dwdpheno.download` counts them), with
    the extra columns ``n_observations, first_year, last_year``.  This downloads the data files.
    """
    net = dict(cache=cache, offline=offline, max_age_days=max_age_days)
    sel = dict(station_id=station_id, name=name, state=state, county=county, city=city, lat=lat,
               lon=lon, radius_km=radius_km, nearest=nearest, bbox=bbox, polygon=polygon,
               reporter=reporter, active=active)
    out = select_stations(station_table(**net), **sel)
    if crops is None:
        if years is not None or quality is not None or quality_level is not None:
            raise ValueError("years / quality / quality_level need crops=")
        return out
    from ._download import download   # here to avoid an import cycle

    cols = list(out.columns) + ["n_observations", "first_year", "last_year"]
    if out.empty:
        return pd.DataFrame({c: pd.Series(dtype=out[c].dtype if c in out else "int64")
                             for c in cols})
    obs = download(crops, years, partition=partition, quality=quality,
                   quality_level=quality_level, verbose=verbose, progress=progress, **sel, **net)
    stats = (obs.assign(year=pd.to_numeric(obs["year"]))
             .groupby("station_id")["year"].agg(["size", "min", "max"])
             .rename(columns={"size": "n_observations", "min": "first_year", "max": "last_year"}))
    out = out.merge(stats, left_on="station_id", right_index=True, how="inner")
    for c in ("n_observations", "first_year", "last_year"):
        out[c] = out[c].astype("int64")
    return out[cols].reset_index(drop=True)
