"""BBCH time series (season detection + PCHIP curve) and day-of-year summary."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ._quality import (QUALITY_BYTE, QUALITY_LEVEL, QualityArg, filter_quality, meanings,
                       quality_bytes)
from ._text import as_list, select_names

SERIES_COLUMNS = ["kind", "station_id", "crop", "season", "date", "t", "season_doy", "bbch",
                  "phase_id", "phase_name", "quality_byte", "quality_byte_meaning",
                  "quality_level", "quality_level_meaning"]
SUMMARY_COLUMNS = ["station_id", "crop", "objekt_id", "phase_id", "phase_name", "bbch_code", "n",
                   "first_year", "last_year", "mean_doy", "sd_doy", "min_doy", "max_doy",
                   "trend_days_per_decade", "n_not_flagged", "n_corrected", "n_confirmed",
                   "n_doubtful", "n_incorrect", "n_no_quality_byte", "quality_levels"]
BBCH_DROP = 20        # a BBCH drop larger than this starts a new cycle
MAX_GAP_DAYS = 300    # so does a gap longer than this
EPOCH = np.datetime64("1970-01-01", "D")

BBCH_PRINCIPAL_STAGES = {
    0: "Germination / sprouting", 1: "Leaf development", 2: "Side shoots / tillering",
    3: "Stem elongation", 4: "Booting / harvestable parts", 5: "Inflorescence emergence",
    6: "Flowering", 7: "Fruit development", 8: "Ripening", 9: "Senescence",
}


# ---------------------------------------------------------------------------------------------
#  PCHIP (Fritsch-Carlson monotone piecewise-cubic Hermite)
# ---------------------------------------------------------------------------------------------

def _edge_slope(h0: float, h1: float, d0: float, d1: float) -> float:
    s = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
    if np.sign(s) != np.sign(d0):
        return 0.0
    if np.sign(d0) != np.sign(d1) and abs(s) > abs(3 * d0):
        return 3 * d0
    return s


def pchip_slopes(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Node derivatives of the shape-preserving PCHIP interpolant (Fritsch & Carlson 1980).

    Interior: weighted harmonic mean of the neighbouring secants, zero at local extrema;
    ends: one-sided three-point estimate limited to keep the shape.
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    h = np.diff(x)
    d = np.diff(y) / h
    n = x.size
    m = np.zeros(n)
    if n == 2:
        m[:] = d[0]
        return m
    for k in range(1, n - 1):
        if d[k - 1] * d[k] > 0:
            w1, w2 = 2 * h[k] + h[k - 1], h[k] + 2 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k])
    m[0] = _edge_slope(h[0], h[1], d[0], d[1])
    m[-1] = _edge_slope(h[-1], h[-2], d[-1], d[-2])
    return m


def pchip(x, y, xi) -> np.ndarray:
    """Evaluate the PCHIP interpolant through ``(x, y)`` (strictly increasing ``x``) at ``xi``."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    xi = np.asarray(xi, float)
    if x.size == 1:
        return np.full(xi.shape, y[0])
    m = pchip_slopes(x, y)
    k = np.clip(np.searchsorted(x, xi, side="right") - 1, 0, x.size - 2)
    h = x[k + 1] - x[k]
    s = (xi - x[k]) / h
    h00 = (1 + 2 * s) * (1 - s) ** 2
    h10 = s * (1 - s) ** 2
    h01 = s ** 2 * (3 - 2 * s)
    h11 = s ** 2 * (s - 1)
    return h00 * y[k] + h10 * h * m[k] + h01 * y[k + 1] + h11 * h * m[k + 1]


# ---------------------------------------------------------------------------------------------
#  Series
# ---------------------------------------------------------------------------------------------

def _days(dates) -> np.ndarray:
    """Days since 1970-01-01 (float, NaN for missing dates)."""
    d = pd.to_datetime(pd.Series(dates), errors="coerce")
    return ((d - pd.Timestamp("1970-01-01")) / pd.Timedelta(days=1)).to_numpy(dtype=float)


def _iso(t: np.ndarray) -> pd.Series:
    return pd.Series(pd.to_datetime((EPOCH + np.floor(t).astype("int64")).astype("datetime64[s]")))


def _filter(obs: pd.DataFrame, station_id=None, crops=None, quality: QualityArg = None,
            quality_level: QualityArg = None) -> pd.DataFrame:
    ids = as_list(station_id)
    if ids is not None:
        obs = obs[obs["station_id"].isin([int(i) for i in ids])]
    qs = as_list(crops)
    if qs:
        names = ["crop"] + [c for c in ("crop_de",) if c in obs.columns]
        pairs = obs[names].drop_duplicates()
        cands = [list(r) for r in pairs.itertuples(index=False)]
        hit = {i for q in qs for i in select_names(q, cands)}
        keep = {pairs.iloc[i]["crop"] for i in hit}
        obs = obs[obs["crop"].isin(keep)]
    return filter_quality(obs, quality, quality_level)


def split_cycles(t: np.ndarray, bbch: np.ndarray) -> np.ndarray:
    """Cycle number for each point (``t`` sorted): new cycle on a BBCH drop > 20 or a gap > 300 d."""
    cyc = np.zeros(t.size, dtype=int)
    m = -np.inf
    c = 0
    for i in range(t.size):
        if i and (bbch[i] < m - BBCH_DROP or t[i] - t[i - 1] > MAX_GAP_DAYS):
            c += 1
            m = -np.inf
        m = max(m, bbch[i])
        cyc[i] = c
    return cyc


def _col(df: pd.DataFrame, name: str, numeric: bool = False) -> np.ndarray:
    if name not in df.columns:
        return np.full(len(df), np.nan if numeric else None, dtype=float if numeric else object)
    if numeric:
        return pd.to_numeric(df[name], errors="coerce").astype(float).to_numpy()
    return df[name].to_numpy(object)


def series(obs: pd.DataFrame, station_id=None, crops=None, step_days: float = 1,
           quality: QualityArg = None, quality_level: QualityArg = None) -> pd.DataFrame:
    """BBCH time series per station, crop and season, with a smooth PCHIP curve.

    Seasons are detected from the data, because DWD's reference year (*Referenzjahr*) is not a
    crop cycle: per
    ``(station_id, crop)`` the observations with a numeric BBCH code that pass ``quality`` /
    ``quality_level`` (default: all) are sorted by date; a BBCH drop of more than 20 or a gap of
    more than 300 days starts a new cycle, and ``season`` is the calendar year of the cycle's last
    point (the harvest year); if that is not later than the previous cycle's season, it is the
    previous season + 1 (an unfinished cycle: sown, not yet harvested).  ``bbch`` and ``t`` are
    rounded to 2 decimals.

    Returns rows ``kind, station_id, crop, season, date, t, bbch, phase_id, phase_name,
    quality_byte, quality_byte_meaning, quality_level, quality_level_meaning`` with ``kind`` =
    ``"point"`` (an observation) or ``"curve"`` (sampled every ``step_days`` from the first to the
    last point, ends included; phase and quality columns empty); ``t`` = days since 1970-01-01;
    ``season_doy`` = day of the season counted from 1 January of the season (harvest) year,
    ``t - days(season-01-01) + 1`` (negative for the autumn before), for overlaying seasons,
    stations and crops on one axis.  ``station_id`` and ``crops`` accept lists.
    """
    if step_days <= 0:
        raise ValueError("step_days must be > 0")
    df = _filter(obs, station_id, crops, quality, quality_level)
    bb = pd.to_numeric(df["bbch_code"].astype("string").str.extract(r"^\s*(\d+)", expand=False),
                       errors="coerce")
    keep = bb.notna().astype(bool)
    df, bb = df[keep], bb[keep]
    df = pd.DataFrame({"station_id": pd.to_numeric(df["station_id"]).astype("int64").to_numpy(),
                       "crop": df["crop"].astype(str).to_numpy(),
                       "t": _days(df["date"]),
                       "bbch": bb.astype(float).to_numpy(),
                       "phase_id": _col(df, "phase_id", numeric=True),
                       "phase_name": _col(df, "phase_name"),
                       "quality_byte": _col(df, "quality_byte", numeric=True),
                       "quality_level": _col(df, "quality_level", numeric=True)})
    df = df[np.isfinite(df["t"])]
    out = []
    for (sid, crop), g in df.groupby(["station_id", "crop"], sort=True):
        g = g.sort_values(["t", "bbch"], kind="stable")
        t, b = g["t"].to_numpy(), g["bbch"].to_numpy()
        cyc = split_cycles(t, b)
        prev = None
        for c in np.unique(cyc):
            sel = cyc == c
            gp = g[sel]
            tt, bb_ = t[sel], b[sel]
            season = int(str(EPOCH + np.timedelta64(int(tt[-1]), "D"))[:4])
            if prev is not None and season <= prev:   # unfinished cycle: sown, not yet harvested
                season = prev + 1
            prev = season
            out.append(pd.DataFrame({"kind": "point", "station_id": sid, "crop": crop,
                                     "season": season, "t": tt, "bbch": bb_,
                                     "phase_id": gp["phase_id"].to_numpy(),
                                     "phase_name": gp["phase_name"].to_numpy(),
                                     "quality_byte": gp["quality_byte"].to_numpy(),
                                     "quality_level": gp["quality_level"].to_numpy()}))
            ux = np.unique(tt)
            if ux.size < 2:
                continue
            uy = np.array([bb_[tt == u].max() for u in ux])
            ts = np.arange(ux[0], ux[-1], float(step_days))
            ts = np.append(ts, ux[-1]) if ts[-1] < ux[-1] else ts
            out.append(pd.DataFrame({"kind": "curve", "station_id": sid, "crop": crop,
                                     "season": season, "t": np.round(ts, 2),
                                     "bbch": np.round(pchip(ux, uy, ts), 2),
                                     "phase_id": np.nan, "phase_name": None,
                                     "quality_byte": np.nan, "quality_level": np.nan}))
    if not out:
        return pd.DataFrame({c: pd.Series(dtype=object) for c in SERIES_COLUMNS})
    res = pd.concat(out, ignore_index=True)
    res["date"] = _iso(res["t"].to_numpy())
    res["season"] = res["season"].astype("int64")
    jan1 = (pd.to_datetime(res["season"].astype(str) + "-01-01")
            - pd.Timestamp("1970-01-01")) / pd.Timedelta(days=1)
    res["season_doy"] = np.round(res["t"].to_numpy() - jan1.to_numpy() + 1, 2)
    for c in ("phase_id", "quality_byte", "quality_level"):
        res[c] = pd.to_numeric(res[c], errors="coerce").astype("Int64")
    res["quality_byte_meaning"] = meanings(res["quality_byte"], QUALITY_BYTE)
    res["quality_level_meaning"] = meanings(res["quality_level"], QUALITY_LEVEL)
    for c in ("phase_name", "kind", "crop"):
        res[c] = res[c].astype("string")
    res["season"] = res["season"].astype("int64")
    return res[SERIES_COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------------------------
#  Summary
# ---------------------------------------------------------------------------------------------

_QB_COUNTS = {"n_not_flagged": 1, "n_corrected": 2, "n_confirmed": 3, "n_doubtful": 5,
              "n_incorrect": 8, "n_no_quality_byte": 0}


def summary(obs: pd.DataFrame, quality: QualityArg = None,
            quality_level: QualityArg = None) -> pd.DataFrame:
    """Day-of-year statistics per ``(station_id, crop, objekt_id, phase_id)``.

    Columns ``station_id, crop, objekt_id, phase_id, phase_name, bbch_code, n, first_year,
    last_year, mean_doy, sd_doy, min_doy, max_doy, trend_days_per_decade`` (sample SD; trend =
    OLS slope of day of year on year x 10, missing when n < 3; mean/sd/trend rounded to 2
    decimals), then the observations per quality byte ``n_not_flagged, n_corrected, n_confirmed,
    n_doubtful, n_incorrect, n_no_quality_byte`` (a missing byte counts as 0) and
    ``quality_levels``, the distinct quality levels ``;``-joined ascending (e.g. ``"7;10"``).
    ``quality`` / ``quality_level`` keep only those codes first (default: all).
    """
    df = filter_quality(obs, quality, quality_level).dropna(subset=["day_of_year", "year"])
    if df.empty:
        return pd.DataFrame({c: pd.Series(dtype=object) for c in SUMMARY_COLUMNS})
    lv = (pd.to_numeric(df["quality_level"], errors="coerce") if "quality_level" in df.columns
          else pd.Series(np.nan, index=df.index))
    df = df.assign(_doy=pd.to_numeric(df["day_of_year"]).astype(float),
                   _yr=pd.to_numeric(df["year"]).astype(float),
                   _qb=quality_bytes(df), _ql=lv)
    rows = []
    for (sid, crop, oid, pid), g in df.groupby(["station_id", "crop", "objekt_id", "phase_id"],
                                               sort=True):
        y, x = g["_doy"].to_numpy(), g["_yr"].to_numpy()
        n = y.size
        trend = np.nan
        if n >= 3 and np.ptp(x) > 0:
            xc = x - x.mean()
            trend = 10.0 * float(np.sum(xc * (y - y.mean())) / np.sum(xc * xc))
        first = g.iloc[0]
        levels = sorted(int(v) for v in g["_ql"].dropna().unique())
        row = {"station_id": sid, "crop": crop, "objekt_id": oid, "phase_id": pid,
               "phase_name": first.get("phase_name"), "bbch_code": first.get("bbch_code"),
               "n": n, "first_year": int(x.min()), "last_year": int(x.max()),
               "mean_doy": round(float(y.mean()), 2),
               "sd_doy": round(float(y.std(ddof=1)), 2) if n > 1 else np.nan,
               "min_doy": int(y.min()), "max_doy": int(y.max()),
               "trend_days_per_decade": round(trend, 2),
               "quality_levels": ";".join(str(v) for v in levels) or None}
        for col, code in _QB_COUNTS.items():
            row[col] = int((g["_qb"] == code).sum())
        rows.append(row)
    res = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    for c in ("station_id", "n", "first_year", "last_year", "min_doy", "max_doy", *_QB_COUNTS):
        res[c] = res[c].astype("int64")
    for c in ("objekt_id", "phase_id"):
        res[c] = pd.to_numeric(res[c]).astype("Int64")
    for c in ("crop", "phase_name", "bbch_code", "quality_levels"):
        res[c] = res[c].astype("string")
    return res
