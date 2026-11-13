"""Plots (matplotlib): BBCH series of several stations / crops / seasons, phase-date trends."""
from __future__ import annotations

import datetime
import math
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

from ._http import NoMatchError
from ._quality import QualityArg
from ._series import BBCH_PRINCIPAL_STAGES, _filter, series
from ._text import as_list, select_names

FLAG_COLOUR = "#d00000"
QUALITY_LABELS = {"ok": "not flagged", "checked": "corrected / confirmed (2, 3)",
                  "flagged": "doubtful / incorrect (5, 8)"}
LINESTYLES = ["-", "--", ":", "-.", (0, (5, 1, 1, 1, 1, 1)), (0, (8, 2)), (0, (1, 3))]
KEY_COLUMN = {"crop": "crop", "station": "station_id", "season": "season"}
SEASON_DOY_LABEL = "day of season (1 = 1 January of the harvest year)"


def _plt():
    try:
        import matplotlib.pyplot as plt
    except ImportError as e:  # pragma: no cover
        raise ImportError("plotting needs matplotlib: pip install dwdpheno[plot]") from e
    return plt


def _station_names(obs: pd.DataFrame) -> Dict[int, str]:
    if "station_name" not in obs.columns:
        return {}
    d = obs[["station_id", "station_name"]].dropna().drop_duplicates("station_id")
    return {int(i): str(n) for i, n in zip(d["station_id"], d["station_name"])}


def _label(key: str, value, names: Dict[int, str]) -> str:
    if key == "station":
        name = names.get(int(value))
        return f"{name} ({int(value)})" if name else f"station {int(value)}"
    return str(value)


def _colours(n: int, key: str) -> List:
    plt = _plt()
    if key == "season" and n > 1:
        cmap = plt.get_cmap("viridis")
        return [cmap(v) for v in np.linspace(0.05, 0.9, n)]
    if n <= 10:
        return list(plt.get_cmap("tab10").colors[:max(n, 1)])
    cmap = plt.get_cmap("tab20")
    return [cmap(i % 20) for i in range(n)]


def _quality_class(qb: pd.Series) -> pd.Series:
    q = pd.to_numeric(qb, errors="coerce").fillna(0).astype(int)
    return q.map(lambda v: "flagged" if v in (5, 8) else "checked" if v in (2, 3) else "ok")


def _draw_points(ax, x, pt: pd.DataFrame, col, used: set) -> None:
    cls = _quality_class(pt["quality_byte"]).to_numpy()
    for k in ("ok", "checked", "flagged"):
        sel = cls == k
        if not sel.any():
            continue
        used.add(k)
        xs, ys = x[sel], pt["bbch"].to_numpy()[sel]
        if k == "ok":
            ax.plot(xs, ys, "o", color=col, ms=4.5, mec="white", mew=0.6, zorder=3)
        elif k == "checked":
            ax.plot(xs, ys, "o", mfc="white", mec=col, ms=5, mew=1.3, zorder=3)
        else:
            ax.plot(xs, ys, "X", mfc=col, mec=FLAG_COLOUR, ms=8, mew=1.2, zorder=4)


def _quality_legend(ax, used: set) -> None:
    from matplotlib.lines import Line2D
    grey = "0.45"
    proxies = {
        "ok": Line2D([], [], ls="", marker="o", color=grey, ms=6, mec="white", mew=0.6),
        "checked": Line2D([], [], ls="", marker="o", mfc="white", mec=grey, ms=6, mew=1.3),
        "flagged": Line2D([], [], ls="", marker="X", mfc=grey, mec=FLAG_COLOUR, ms=8, mew=1.2),
    }
    keys = [k for k in ("ok", "checked", "flagged") if k in used]
    if keys:
        ax.legend([proxies[k] for k in keys], [QUALITY_LABELS[k] for k in keys],
                  loc="upper center", bbox_to_anchor=(0.5, -0.07 if ax.get_xlabel() == "" else -0.13),
                  ncol=len(keys), frameon=False, fontsize=8,
                  title="DWD quality of the observations", title_fontsize=8)


def _bbch_axis(ax) -> None:
    ax.set_ylim(-4, 100)
    ax.set_yticks([10 * k for k in BBCH_PRINCIPAL_STAGES])
    ax.set_yticklabels([f"{10 * k:02d}  {v}" for k, v in BBCH_PRINCIPAL_STAGES.items()],
                       fontsize=8)
    ax.grid(True, axis="y", alpha=0.3)


def _date_axis(ax) -> None:
    import matplotlib.dates as mdates
    loc = mdates.AutoDateLocator()
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))


def _month_ticks(lo: float, hi: float):
    """(day-of-season, label) for the first of each month, previous year included."""
    jan1 = datetime.date(2002, 1, 1)                    # a non-leap reference year
    out = []
    for year in (2001, 2002, 2003):
        for m in range(1, 13):
            d = (datetime.date(year, m, 1) - jan1).days + 1
            if lo <= d <= hi:
                out.append((d, datetime.date(year, m, 1).strftime("%b")))
    return out


def _season_doy_axis(ax, lo: float, hi: float, label: bool = True) -> None:
    pad = max(5.0, 0.02 * (hi - lo))
    ax.set_xlim(lo - pad, hi + pad)
    ticks = _month_ticks(lo - pad, hi + pad)
    ax.set_xticks([d for d, _ in ticks])
    ax.set_xticklabels([m for _, m in ticks], fontsize=8)
    ax.axvline(1, color="0.6", lw=0.8, ls=":", zorder=0)
    ax.grid(True, axis="x", alpha=0.15)
    if label:
        ax.set_xlabel(SEASON_DOY_LABEL, fontsize=9)


def _filter_seasons(s: pd.DataFrame, years) -> pd.DataFrame:
    from ._download import parse_years
    yr = parse_years(years)
    if yr is None:
        return s
    lo, hi, explicit = yr
    s = s[s["season"].between(lo, hi)]
    return s[s["season"].isin(explicit)] if explicit is not None else s


def plot_series(obs: pd.DataFrame, station_id=None, crops=None, years=None, x: str = "date",
                color_by: str = "crop", facet: Optional[str] = None,
                quality: QualityArg = None, quality_level: QualityArg = None,
                step_days: float = 1, ax=None):
    """Plot BBCH observations and their smooth PCHIP curves for several stations, crops and seasons.

    Parameters
    ----------
    obs : observations from :func:`dwdpheno.download`.
    station_id, crops : one or several stations / crops (default: everything in ``obs``).
    years : seasons to show (an int, ``(y0, y1)`` or a list).
    x : ``"date"`` (real dates) or ``"season_doy"`` (day of the season; overlays seasons,
        stations and crops on one axis).
    color_by : ``"crop"``, ``"station"`` or ``"season"``.  A second varying key among crop /
        station (and season when ``x="season_doy"``) gets distinct line styles.
    facet : ``None`` (one axes), ``"station"`` or ``"crop"`` (small multiples, shared axes).
    quality, quality_level : filter the observations as in :func:`dwdpheno.series`.  The markers
        show the DWD quality: filled = not flagged, hollow = corrected / confirmed, red-edged
        cross = doubtful / incorrect.
    ax : draw into this axes (only without ``facet``).

    Returns the axes, or a list of axes with ``facet``.
    """
    if x not in ("date", "season_doy"):
        raise ValueError(f"x must be 'date' or 'season_doy', got {x!r}")
    if color_by not in KEY_COLUMN:
        raise ValueError(f"color_by must be 'crop', 'station' or 'season', got {color_by!r}")
    if facet not in (None, "station", "crop"):
        raise ValueError(f"facet must be None, 'station' or 'crop', got {facet!r}")
    if facet is not None and facet == color_by:
        raise ValueError("facet and color_by must differ")
    if facet is not None and ax is not None:
        raise ValueError("ax= cannot be combined with facet=")
    plt = _plt()
    from matplotlib.lines import Line2D

    s = _filter_seasons(series(obs, station_id=station_id, crops=crops, step_days=step_days,
                               quality=quality, quality_level=quality_level), years)
    if s.empty:
        raise NoMatchError("no BBCH observations to plot for this selection")
    names = _station_names(obs)

    cvals = sorted(s[KEY_COLUMN[color_by]].unique())
    colour = dict(zip(cvals, _colours(len(cvals), color_by)))
    style_key = None
    candidates = ["crop", "station"] + (["season"] if x == "season_doy" else [])
    for k in candidates:
        if k not in (color_by, facet) and 1 < s[KEY_COLUMN[k]].nunique() <= len(LINESTYLES):
            style_key = k
            break
    svals = sorted(s[KEY_COLUMN[style_key]].unique()) if style_key else []
    style = dict(zip(svals, LINESTYLES))

    fvals = sorted(s[KEY_COLUMN[facet]].unique()) if facet else [None]
    ncols = 1
    if facet:
        n = len(fvals)
        ncols = 1 if n <= 3 else 2
        nrows = math.ceil(n / ncols)
        fig, grid = plt.subplots(nrows, ncols, sharex=True, sharey=True, squeeze=False,
                                 figsize=(11 if ncols == 1 else 13, 1.0 + 2.9 * nrows),
                                 constrained_layout=True)
        axes = list(grid.ravel())
        for extra in axes[n:]:
            extra.set_visible(False)
        axes = axes[:n]
    else:
        if ax is None:
            _, ax = plt.subplots(figsize=(11, 4.8), constrained_layout=True)
        axes = [ax]

    used: set = set()
    for a, fv in zip(axes, fvals):
        sub = s if fv is None else s[s[KEY_COLUMN[facet]] == fv]
        for (sid, crop, season), g in sub.groupby(["station_id", "crop", "season"], sort=True):
            key_of = {"crop": crop, "station": sid, "season": season}
            col = colour[key_of[color_by]]
            ls = style.get(key_of[style_key], "-") if style_key else "-"
            xcol = (pd.to_datetime(g["date"]) if x == "date" else g["season_doy"]).to_numpy()
            cv = (g["kind"] == "curve").fillna(False).to_numpy(dtype=bool)
            if cv.any():
                a.plot(xcol[cv], g["bbch"].to_numpy()[cv], color=col, lw=1.6, ls=ls)
            _draw_points(a, xcol[~cv], g[~cv], col, used)
        _bbch_axis(a)
        if fv is not None:
            a.set_title(_label(facet, fv, names), fontsize=10)
    lo, hi = float(s["season_doy"].min()), float(s["season_doy"].max())
    for i, a in enumerate(axes):
        bottom = i >= len(axes) - ncols
        if x == "date":
            _date_axis(a)
        else:
            _season_doy_axis(a, lo, hi, label=bottom)
        if i % ncols == 0:
            a.set_ylabel("BBCH")

    # legends: colour (+ line style) on the first axes, quality under the last one
    first = axes[0]
    handles = [Line2D([], [], color=colour[v], lw=2) for v in cvals]
    labels = [_label(color_by, v, names) for v in cvals]
    if style_key:
        handles += [Line2D([], [], color="0.3", lw=1.6, ls=style[v]) for v in svals]
        labels += [_label(style_key, v, names) for v in svals]
    many = len(handles) > 8
    leg = first.legend(handles, labels, loc="upper left", frameon=False,
                       fontsize=8 if many else 9, ncol=2 if many else 1)
    _quality_legend(axes[-1], used)
    if axes[-1] is first:
        first.add_artist(leg)          # keep it next to the quality legend

    if not facet:
        title = []
        if s["station_id"].nunique() == 1 and color_by != "station":
            title.append(_label("station", s["station_id"].iloc[0], names))
        if s["crop"].nunique() == 1 and color_by != "crop":
            title.append(str(s["crop"].iloc[0]))
        if s["season"].nunique() == 1 and color_by != "season":
            title.append(f"season {int(s['season'].iloc[0])}")
        if title:
            first.set_title(" – ".join(title))
        return first
    return axes


def plot_station(obs: pd.DataFrame, station_id: int, crops=None, ax=None,
                 years: Union[None, int, Sequence[int]] = None, step_days: float = 1,
                 quality: QualityArg = None, quality_level: QualityArg = None):
    """One station's BBCH observations and smooth curves on a date axis, one colour per crop.

    Shorthand for ``plot_series(obs, station_id, crops, years, x="date", color_by="crop")``.
    """
    return plot_series(obs, station_id=station_id, crops=crops, years=years, x="date",
                       color_by="crop", quality=quality, quality_level=quality_level,
                       step_days=step_days, ax=ax)


def _select_phases(df: pd.DataFrame, phases) -> pd.DataFrame:
    qs = as_list(phases)
    if not qs:
        return df
    pid = pd.to_numeric(df["phase_id"], errors="coerce")
    names = df[["phase_name"]].dropna().drop_duplicates()["phase_name"].tolist()
    keep_ids, keep_names = set(), set()
    for q in qs:
        if isinstance(q, (int, np.integer)) or str(q).strip().isdigit():
            keep_ids.add(int(q))
        else:
            keep_names.update(names[i] for i in select_names(str(q), [[n] for n in names]))
    return df[(pid.isin(keep_ids) | df["phase_name"].isin(keep_names)).astype(bool)]


def plot_phase_trend(obs: pd.DataFrame, phases=None, station_id=None, crops=None, years=None,
                     quality: QualityArg = None, quality_level: QualityArg = None, ax=None):
    """Day of year of phenological phases against year, with an OLS trend line per phase.

    ``phases`` are phase ids or (English) phase names (exact name first, otherwise word
    prefixes; default: every phase).  Observations of all selected stations are pooled per
    ``(crop, phase)``; the legend gives the trend in days per decade (negative = earlier).
    For a single station the trend equals :func:`dwdpheno.summary`'s ``trend_days_per_decade``.
    Returns the axes.
    """
    plt = _plt()
    from ._download import parse_years

    df = _filter(obs, station_id, crops, quality, quality_level)
    df = df.dropna(subset=["day_of_year", "year"])
    yr = parse_years(years)
    if yr is not None:
        lo, hi, explicit = yr
        y = pd.to_numeric(df["year"])
        keep = y.between(lo, hi)
        if explicit is not None:
            keep &= y.isin(explicit)
        df = df[keep.astype(bool)]
    df = _select_phases(df, phases)
    if df.empty:
        raise NoMatchError("no observations of these phases to plot")
    df = df.assign(_x=pd.to_numeric(df["year"]).astype(float),
                   _y=pd.to_numeric(df["day_of_year"]).astype(float))
    groups = sorted(df.groupby(["crop", "phase_id"], sort=False),
                    key=lambda kv: (str(kv[0][0]), kv[1]["_y"].mean()))
    multi_crop = df["crop"].nunique() > 1
    if ax is None:
        _, ax = plt.subplots(figsize=(11, 5.6), constrained_layout=True)
    cols = _colours(len(groups), "phase")
    for (crop, _pid), g in groups:
        col = cols.pop(0)
        xs, ys = g["_x"].to_numpy(), g["_y"].to_numpy()
        name = g["phase_name"].dropna().iloc[0] if g["phase_name"].notna().any() else f"phase {_pid}"
        label = f"{crop} – {name}" if multi_crop else str(name)
        ax.plot(xs, ys, "o", color=col, ms=3.5, alpha=0.55, mew=0)
        if len(xs) >= 3 and np.ptp(xs) > 0:
            slope, icpt = np.polyfit(xs, ys, 1)
            xx = np.array([xs.min(), xs.max()])
            ax.plot(xx, icpt + slope * xx, color=col, lw=2.2)
            label += f": {10 * slope:+.1f} d/decade (n={len(xs)})"
        else:
            label += f": no trend (n={len(xs)})"
        ax.plot([], [], "o-", color=col, label=label)
    lo, hi = ax.get_ylim()
    ticks = [(d, m) for d, m in _month_ticks(lo, hi) if 1 <= d <= 366]
    ax.set_yticks([d for d, _ in ticks])
    ax.set_yticklabels([f"{m} 1  ({d})" for d, m in ticks], fontsize=8)
    ax.set_ylabel("day of year")
    ax.set_xlabel("year (DWD reference year)")
    ax.grid(True, alpha=0.25)
    names = _station_names(df)
    ids = sorted(df["station_id"].unique())
    where = (_label("station", ids[0], names) if len(ids) == 1 else f"{len(ids)} stations")
    crop_part = "" if multi_crop else f"{df['crop'].iloc[0]} – "
    ax.set_title(f"{crop_part}phase dates and trends, {where}")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, frameon=False,
              fontsize=8.5, title="trend (OLS), days per decade; negative = earlier",
              title_fontsize=8.5)
    return ax
