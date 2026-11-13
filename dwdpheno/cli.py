"""Command line interface: ``dwdpheno <command> [options]`` (also ``python -m dwdpheno``).

Exit codes: 0 ok, 1 usage error, 2 no match, 3 network / IO error.
Progress goes to stderr as ``PROGRESS <i> <n> <text>``, errors as ``ERROR <text>``.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

import pandas as pd

from . import __version__
from ._http import NetworkError, NoMatchError

EXIT_OK, EXIT_USAGE, EXIT_NOMATCH, EXIT_IO = 0, 1, 2, 3

_OBS_DTYPES = {c: "string" for c in ("station_name", "state", "county", "crop", "crop_de",
                                     "species", "phase_name", "bbch_code",
                                     "quality_byte_meaning", "quality_level_meaning", "reporter",
                                     "partition", "source_file")}


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # exit code 1 instead of argparse's 2
        raise _UsageError(message)


def _stderr(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def write_table(df: pd.DataFrame, fmt: str = "csv", out: Optional[str] = None) -> None:
    """CSV (``,``-separated, UTF-8, empty = missing) or JSON (array of objects, null = missing)."""
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%Y-%m-%d")
    if fmt == "json":
        text = df.to_json(orient="records", force_ascii=False, double_precision=10)
    else:
        text = df.to_csv(index=False, lineterminator="\n")
    data = text.encode("utf-8")
    if out:
        p = Path(out).expanduser()
        if p.parent and not p.parent.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    else:
        sys.stdout.flush()
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()


def read_obs(path: str) -> pd.DataFrame:
    """Read observations written by ``dwdpheno download`` (CSV or JSON)."""
    if str(path).lower().endswith(".json"):
        df = pd.read_json(path, orient="records", dtype=False)
    else:
        df = pd.read_csv(path, dtype=_OBS_DTYPES)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    return df


def _add_global(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("global options")
    g.add_argument("--data", metavar="DIR", default=argparse.SUPPRESS,
                   help="reference data folder (default: bundled; env DWDPHENO_DATA)")
    g.add_argument("--cache", metavar="DIR", default=argparse.SUPPRESS,
                   help="cache folder (env DWDPHENO_CACHE); 'off' disables the cache")
    g.add_argument("--offline", action="store_true", default=argparse.SUPPRESS,
                   help="use only cached files")
    g.add_argument("--quiet", action="store_true", default=argparse.SUPPRESS,
                   help="no progress output")
    g.add_argument("--max-age-days", type=float, metavar="D", default=argparse.SUPPRESS,
                   help="refresh listings / metadata / recent files older than D days (default 1)")


def _add_output(p: argparse.ArgumentParser) -> None:
    p.add_argument("--format", choices=("csv", "json"), default="csv")
    p.add_argument("--out", metavar="FILE", help="output file (default: stdout)")


def _add_selection(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("station selection (all criteria AND-ed)")
    g.add_argument("--station-id", metavar="ID,ID", help="exact station ids")
    g.add_argument("--name", help="station-name match (comma = OR)")
    g.add_argument("--state", help="federal state match")
    g.add_argument("--county", help='county match, e.g. "Kassel rural district" or "Landkreis Kassel"')
    g.add_argument("--city", help="centre = best-matching place")
    g.add_argument("--lat", type=float, help="centre latitude")
    g.add_argument("--lon", type=float, help="centre longitude")
    g.add_argument("--radius", type=float, metavar="KM", help="km around the centre (default 25)")
    g.add_argument("--nearest", type=int, metavar="K", help="the K closest stations to the centre")
    g.add_argument("--bbox", metavar="S,W,N,E", help="lat/lon box")
    g.add_argument("--polygon", metavar='"LAT LON;LAT LON;..."', help="even-odd polygon")
    g.add_argument("--reporter", choices=("annual", "immediate", "both"), default="both")
    g.add_argument("--active", action="store_true", help="only stations still active")


def _add_quality(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("data quality (default: keep everything)")
    g.add_argument("--quality", metavar="1,2,3",
                   help="keep only these quality bytes: 1 not flagged, 2 corrected, 3 confirmed "
                        "despite flag, 5 doubtful, 8 incorrect, 0 no quality byte")
    g.add_argument("--quality-level", metavar="7,10",
                   help="keep only these quality levels: 1 pre-load check only, 2 pre-load check "
                        "(immediate reporters), 7 ROUTKLI checked, 10 ROUTKLI checked + corrected")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="dwdpheno",
                     description="Download DWD plant-phenology observations.",
                     epilog="Data: Deutscher Wetterdienst (DWD), CC BY 4.0.")
    _add_global(parser)
    sub = parser.add_subparsers(dest="command", metavar="<command>", parser_class=_Parser)

    def cmd(name: str, help_: str) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_, description=help_)
        _add_global(p)
        return p

    p = cmd("stations", "list / select stations (with --crops: only stations that have data)")
    _add_selection(p)
    g = p.add_argument_group("only stations with observations of these crops")
    g.add_argument("--crops", metavar="A,B",
                   help="keep stations with data for these crops; adds n_observations, "
                        "first_year, last_year")
    g.add_argument("--years", metavar="Y0-Y1|Y|Y,Y", help="with --crops: 2000-2020, 2005 or 1990,1995")
    g.add_argument("--partition", choices=("historical", "recent", "both"), default="both")
    _add_quality(p)
    _add_output(p)

    p = cmd("crops", "species in the DWD catalog")
    _add_output(p)

    p = cmd("phases", "phase definitions with BBCH codes")
    p.add_argument("--crops", metavar="A,B")
    _add_output(p)

    p = cmd("download", "download tidy observations")
    p.add_argument("--crops", metavar="A,B", required=True)
    p.add_argument("--years", metavar="Y0-Y1|Y|Y,Y", help="2000-2020, 2005 or 1990,1995")
    p.add_argument("--partition", choices=("historical", "recent", "both"), default="both")
    _add_selection(p)
    _add_quality(p)
    _add_output(p)

    p = cmd("series", "BBCH time series with a smooth PCHIP curve")
    p.add_argument("--in", dest="infile", metavar="OBS.csv", required=True)
    p.add_argument("--station-id", metavar="ID,ID")
    p.add_argument("--crops", metavar="A,B")
    p.add_argument("--step-days", type=float, default=1.0)
    _add_quality(p)
    _add_output(p)

    p = cmd("summary", "day-of-year statistics per station, crop and phase")
    p.add_argument("--in", dest="infile", metavar="OBS.csv", required=True)
    _add_quality(p)
    _add_output(p)

    p = cmd("places", "search the bundled place list")
    p.add_argument("--q", required=True, metavar="NAME")
    p.add_argument("--limit", type=int)
    _add_output(p)

    p = cmd("plot", "plot BBCH series of one or several stations / crops / seasons to an image "
                    "(needs matplotlib)")
    p.add_argument("--in", dest="infile", metavar="OBS.csv", required=True)
    p.add_argument("--station-id", metavar="ID,ID", help="one or several stations (default: all)")
    p.add_argument("--crops", metavar="A,B")
    p.add_argument("--years", metavar="Y0-Y1|Y|Y,Y", help="seasons to show")
    p.add_argument("--x", choices=("date", "season_doy"), default="date",
                   help="x axis: real dates, or day of the season (overlays seasons)")
    p.add_argument("--color-by", choices=("crop", "station", "season"), default="crop")
    p.add_argument("--facet", choices=("station", "crop"), help="one panel per station / crop")
    p.add_argument("--step-days", type=float, default=1.0)
    p.add_argument("--out", metavar="FILE.png", required=True)
    p.add_argument("--dpi", type=int, default=150)
    _add_quality(p)

    p = cmd("plot-trend", "plot phase dates against year with OLS trends (needs matplotlib)")
    p.add_argument("--in", dest="infile", metavar="OBS.csv", required=True)
    p.add_argument("--phases", metavar="ID|NAME,...",
                   help="phase ids or English phase names (default: all)")
    p.add_argument("--station-id", metavar="ID,ID", help="one or several stations (default: all)")
    p.add_argument("--crops", metavar="A,B")
    p.add_argument("--years", metavar="Y0-Y1|Y|Y,Y")
    p.add_argument("--out", metavar="FILE.png", required=True)
    p.add_argument("--dpi", type=int, default=150)
    _add_quality(p)

    cmd("version", "print the version")
    return parser


def _selection(a) -> dict:
    return dict(station_id=a.station_id, name=a.name, state=a.state, county=a.county,
                city=a.city, lat=a.lat, lon=a.lon, radius_km=a.radius, nearest=a.nearest,
                bbox=a.bbox, polygon=a.polygon, reporter=a.reporter, active=a.active)


def _run(a) -> int:
    import dwdpheno as dp

    quiet = getattr(a, "quiet", False)
    cache = getattr(a, "cache", None)
    if isinstance(cache, str) and cache.lower() in ("off", "none", "false", "0"):
        cache = False
    net = dict(cache=cache, offline=getattr(a, "offline", False),
               max_age_days=getattr(a, "max_age_days", 1.0))
    progress = None if quiet else (lambda i, n, t: _stderr(f"PROGRESS {i} {n} {t}"))

    if a.command == "version":
        print(__version__)
        return EXIT_OK
    if a.command == "stations":
        df = dp.stations(**_selection(a), crops=a.crops, years=a.years, partition=a.partition,
                         quality=a.quality, quality_level=a.quality_level, progress=progress,
                         **net)
    elif a.command == "crops":
        df = dp.crops(**net)
    elif a.command == "phases":
        df = dp.phases(a.crops, **net)
    elif a.command == "download":
        df = dp.download(a.crops, a.years, partition=a.partition, progress=progress,
                         quality=a.quality, quality_level=a.quality_level,
                         **_selection(a), **net)
    elif a.command == "series":
        df = dp.series(read_obs(a.infile), station_id=a.station_id, crops=a.crops,
                       step_days=a.step_days, quality=a.quality, quality_level=a.quality_level)
    elif a.command == "summary":
        df = dp.summary(read_obs(a.infile), quality=a.quality, quality_level=a.quality_level)
    elif a.command == "places":
        df = dp.places(a.q, limit=a.limit)
    elif a.command in ("plot", "plot-trend"):
        import matplotlib
        matplotlib.use("Agg")
        obs = read_obs(a.infile)
        if a.command == "plot":
            ax = dp.plot_series(obs, station_id=a.station_id, crops=a.crops, years=a.years,
                                x=a.x, color_by=a.color_by, facet=a.facet,
                                step_days=a.step_days, quality=a.quality,
                                quality_level=a.quality_level)
        else:
            ax = dp.plot_phase_trend(obs, phases=a.phases, station_id=a.station_id,
                                     crops=a.crops, years=a.years, quality=a.quality,
                                     quality_level=a.quality_level)
        fig = (ax[0] if isinstance(ax, list) else ax).figure
        Path(a.out).expanduser().parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(a.out, dpi=a.dpi)
        return EXIT_OK
    else:  # pragma: no cover
        raise _UsageError(f"unknown command {a.command!r}")
    write_table(df, a.format, a.out)
    if not quiet and a.out:
        _stderr(f"PROGRESS 1 1 wrote {len(df)} rows to {a.out}")
    if df.empty and a.command in ("stations", "download", "places"):
        return EXIT_NOMATCH
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        a = parser.parse_args(argv)
        if not a.command:
            parser.print_help(sys.stderr)
            return EXIT_USAGE
        if getattr(a, "data", None):
            os.environ["DWDPHENO_DATA"] = a.data
        return _run(a)
    except _UsageError as e:
        _stderr(f"ERROR {e}")
        return EXIT_USAGE
    except ValueError as e:
        _stderr(f"ERROR {e}")
        return EXIT_USAGE
    except NoMatchError as e:
        _stderr(f"ERROR {e}")
        return EXIT_NOMATCH
    except (NetworkError, OSError) as e:
        _stderr(f"ERROR {e}")
        return EXIT_IO
    except ImportError as e:
        _stderr(f"ERROR {e}")
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
