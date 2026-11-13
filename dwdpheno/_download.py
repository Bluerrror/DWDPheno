"""Download tidy phenological observations."""
from __future__ import annotations

import io
import sys
from typing import Callable, Iterable, Optional, Sequence, Set, Tuple, Union

import pandas as pd

from . import _http
from ._text import as_list
from . import _catalog
from ._catalog import PARTITIONS
from ._quality import (QUALITY_BYTE, QUALITY_LEVEL, QualityArg, filter_quality, meanings,
                       parse_codes)
from ._stations import select_stations, station_table

OBS_COLUMNS = ["station_id", "station_name", "latitude", "longitude", "elevation_m", "state",
               "county", "crop", "crop_de", "species", "objekt_id", "phase_id", "phase_name",
               "bbch_code", "year", "date", "day_of_year", "quality_byte", "quality_byte_meaning",
               "quality_level", "quality_level_meaning", "reporter", "partition", "source_file"]


_RAW_COLUMNS = {"Stations_id": "station_id", "Referenzjahr": "year",
                "Qualitaetsniveau": "quality_level", "Objekt_id": "objekt_id",
                "Phase_id": "phase_id", "Eintrittsdatum": "date",
                "Eintrittsdatum_QB": "quality_byte", "Jultag": "day_of_year"}
_INT_COLUMNS = ("station_id", "year", "quality_level", "objekt_id", "phase_id", "quality_byte",
                "day_of_year")

YearsArg = Union[None, int, str, Tuple[int, int], Sequence[int]]
Progress = Callable[[int, int, str], None]


def parse_years(years: YearsArg) -> Optional[Tuple[int, int, Optional[Set[int]]]]:
    """``None``; ``2005``; ``(y0, y1)`` (inclusive range); list of years; or the strings
    ``"2000-2020"``, ``"2005"``, ``"1990,1995"``.  Returns ``(lo, hi, explicit_set_or_None)``."""
    if years is None:
        return None
    if isinstance(years, str):
        s = years.strip()
        if "-" in s and "," not in s:
            a, b = s.split("-", 1)
            years = (int(a), int(b))
        elif "," in s:
            years = [int(y) for y in s.split(",") if y.strip()]
        else:
            years = int(s)
    if isinstance(years, (int,)) and not isinstance(years, bool):
        return int(years), int(years), None
    if isinstance(years, tuple) and len(years) == 2:
        lo, hi = sorted(int(y) for y in years)
        return lo, hi, None
    ys = sorted({int(y) for y in years})
    if not ys:
        raise ValueError("years is empty")
    return ys[0], ys[-1], set(ys)


def parse_observations(raw: bytes, station_ids: Optional[Iterable[int]] = None,
                       years: YearsArg = None, chunksize: int = 500_000) -> pd.DataFrame:
    """Parse a DWD phenology data file, keeping only ``station_ids`` and ``years``."""
    yr = parse_years(years)
    ids = None if station_ids is None else set(int(i) for i in station_ids)
    reader = pd.read_csv(io.BytesIO(raw), sep=";", encoding="cp1252", skipinitialspace=True,
                         usecols=lambda c: c.strip() in _RAW_COLUMNS, dtype=str,
                         chunksize=chunksize)
    parts = []
    for chunk in reader:
        chunk = chunk.rename(columns=lambda c: _RAW_COLUMNS[c.strip()])
        for c in _INT_COLUMNS:
            chunk[c] = pd.to_numeric(chunk[c].str.strip(), errors="coerce")
        keep = chunk["station_id"].notna()
        if ids is not None:
            keep &= chunk["station_id"].isin(ids)
        if yr is not None:
            lo, hi, explicit = yr
            keep &= chunk["year"].between(lo, hi)
            if explicit is not None:
                keep &= chunk["year"].isin(explicit)
        parts.append(chunk[keep])
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=list(_RAW_COLUMNS.values()))
    for c in _INT_COLUMNS:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    df["date"] = pd.to_datetime(df["date"].astype("string").str.strip(), format="%Y%m%d",
                                errors="coerce")
    return df


def _overlaps(f, yr) -> bool:
    if yr is None or f.y0 is None or f.y1 is None:
        return True
    return not (f.y1 < yr[0] or f.y0 > yr[1])


def _empty() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=object) for c in OBS_COLUMNS})


def download(crops: Union[str, Sequence[str]], years: YearsArg = None, *, station_id=None,
             name=None, state=None, county=None, city: Optional[str] = None,
             lat: Optional[float] = None, lon: Optional[float] = None,
             radius_km: Optional[float] = None, nearest: Optional[int] = None, bbox=None,
             polygon=None, reporter: str = "both", active: bool = False,
             partition: str = "both", quality: QualityArg = None,
             quality_level: QualityArg = None, cache=None, offline: bool = False,
             max_age_days: float = 1.0, verbose: bool = False,
             progress: Optional[Progress] = None) -> pd.DataFrame:
    """Download DWD phenological observations as one tidy DataFrame.

    Parameters
    ----------
    crops : crop names in English, German or as DWD file token (``"winter wheat"``, ``"Apfel"``,
        ``"Apfel_fruehe_Reife"``); an exact name selects just that crop, otherwise every word
        must be the start of a word of the name (``"wheat"`` = winter + spring wheat).
    years : ``2005``, ``(2000, 2020)`` (inclusive), ``[1990, 1995]``, or ``None`` for all.
    station_id, name, state, county, city, lat, lon, radius_km, nearest, bbox, polygon, reporter,
    active : station selection, see :func:`dwdpheno.stations`.
    partition : ``"historical"``, ``"recent"`` or ``"both"``.
    quality, quality_level : keep only these DWD quality bytes (``1 2 3 5 8 0``; a missing byte
        counts as 0) / quality levels (``1 2 7 10``), e.g. ``quality=[1, 2, 3]``.  Default: keep
        everything.
    cache, offline, max_age_days : on-disk cache control.
    verbose : print progress to stderr; ``progress(i, n, text)`` receives the same events.

    Returns one row per observation with the columns in :data:`OBS_COLUMNS`; overlapping
    historical/recent rows are de-duplicated (recent wins).
    """
    crop_list = as_list(crops) or []
    if not crop_list:
        raise ValueError("at least one crop is required")
    if reporter not in ("annual", "immediate", "both"):
        raise ValueError(f"reporter must be 'annual', 'immediate' or 'both', got {reporter!r}")
    if partition not in ("historical", "recent", "both"):
        raise ValueError(f"partition must be 'historical', 'recent' or 'both', got {partition!r}")
    reporters = ["annual", "immediate"] if reporter == "both" else [reporter]
    partitions = list(PARTITIONS) if partition == "both" else [partition]
    yr = parse_years(years)
    parse_codes(quality, QUALITY_BYTE, "quality byte")          # validate before any download
    parse_codes(quality_level, QUALITY_LEVEL, "quality level")
    net = dict(cache=cache, offline=offline, max_age_days=max_age_days)

    def report(i: int, n: int, text: str) -> None:
        if progress is not None:
            progress(i, n, text)
        if verbose:
            print(f"[{i}/{n}] {text}", file=sys.stderr, flush=True)

    table = station_table(**net)
    sel = select_stations(table, station_id=station_id, name=name, state=state, county=county,
                          city=city, lat=lat, lon=lon, radius_km=radius_km, nearest=nearest,
                          bbox=bbox, polygon=polygon, reporter=reporter, active=active)
    if sel.empty:
        raise _http.NoMatchError("no station matches the selection")

    plant_table = _catalog.plants(**net)
    all_files = _catalog.data_files(reporters, partitions, **net)
    cat = _catalog.select_crops(crop_list, _catalog._catalog(all_files, plant_table))
    tokens = set(cat["dwd_token"])
    files = [f for f in all_files if f.crop in tokens and _overlaps(f, yr)]
    if not files:
        raise _http.NoMatchError(f"no DWD data file matches crops {crop_list!r}"
                                 " (see dwdpheno.crops())")
    report(0, len(files), f"{len(sel)} stations, {len(files)} files")
    defs = _catalog.load_phase_definitions(reporters, sorted({f.group for f in files}), **net)
    named = _catalog.name_phases(defs, plant_table, _catalog.phase_names(**net))
    token_names = cat.set_index("dwd_token")[["crop", "crop_de", "species"]]

    ids = sel["station_id"].tolist()
    frames = []
    for i, f in enumerate(files, 1):
        report(i, len(files), f.filename)
        obs = parse_observations(_http.fetch(f.url, **net), ids, years)
        if len(obs):
            tn = token_names.loc[f.crop]
            frames.append(obs.assign(reporter=f.reporter, partition=f.partition,
                                     source_file=f.filename, _crop=tn["crop"],
                                     _crop_de=tn["crop_de"], _species=tn["species"]))
    if not frames:
        return _empty()
    out = pd.concat(frames, ignore_index=True)

    # historical/recent overlap: recent wins
    out = out.assign(_p=(out["partition"] != "recent").astype(int))
    out = out.sort_values("_p", kind="stable").drop_duplicates(
        ["station_id", "objekt_id", "phase_id", "year", "reporter"], keep="first").drop(columns="_p")
    out = filter_quality(out, quality, quality_level)     # after the dedupe: recent still wins
    if out.empty:
        return _empty()

    meta = table[["station_id", "station_name", "latitude", "longitude", "elevation_m", "state",
                  "county"]]
    out = out.merge(meta, on="station_id", how="left")
    # names of the row's objekt (English / German / Latin); the file's plant as fallback
    out = out.merge(plant_table, on="objekt_id", how="left")
    for c in ("crop", "crop_de", "species"):
        out[c] = out[c].astype("string").fillna(out["_" + c].astype("string"))
    ph = named[["objekt_id", "phase_id", "phase_name", "bbch_code"]]
    out = out.merge(ph, on=["objekt_id", "phase_id"], how="left")
    missing = out["phase_name"].isna()
    if missing.any():   # phase not defined for this plant: generic English phase name
        generic = _catalog.phase_names(**net).set_index("phase_id")["phase_name"]
        out.loc[missing, "phase_name"] = out.loc[missing, "phase_id"].map(generic)
    out["quality_byte_meaning"] = meanings(out["quality_byte"], QUALITY_BYTE)
    out["quality_level_meaning"] = meanings(out["quality_level"], QUALITY_LEVEL)
    for c in ("reporter", "partition", "source_file", "phase_name", "bbch_code"):
        out[c] = out[c].astype("string")
    out = out[OBS_COLUMNS].sort_values(["crop", "station_id", "year", "date", "phase_id"],
                                       kind="stable").reset_index(drop=True)
    report(len(files), len(files), f"{len(out)} observations")
    return out
