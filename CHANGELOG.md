# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-13

First public release.

### Added
- `stations()` – the DWD phenology station table (annual and immediate reporters) enriched with
  county (BKG VG2500 point-in-polygon, English county types), nearest place (GeoNames) and
  reporter type, with selection
  by id, name, state, county, city, lat/lon + radius, nearest *k*, bounding box, polygon,
  reporter and activity. With `crops=` (and `years=`, `partition=`, quality filters) only the
  stations that have observations of those crops are returned, with `n_observations`,
  `first_year` and `last_year` (`dwdpheno stations --crops ...`).
- `crops()` – catalog of every species on the DWD server with English, German and Latin names
  from DWD's plant table (latest historical file version only).
- `phases()`, `find_bbch()`, `bbch_for()` – English phase names with BBCH codes.
- `download()` – tidy observations with station metadata, plant and phase names, BBCH codes and
  decoded quality flags; historical/recent overlap de-duplicated (recent wins). Crops are named
  in English, German or as DWD token (exact name first, otherwise word prefixes).
- `series()` – BBCH time series with data-driven season detection and a shape-preserving PCHIP
  curve; `summary()` – day-of-year statistics with an OLS trend; `plot_station()`.
- Data quality: `quality=` (DWD quality bytes 1 2 3 5 8 0) and `quality_level=` (1 2 7 10) on
  `download`, `series`, `summary` and `plot_station` (`--quality`, `--quality-level`); by
  default nothing is filtered. `series` point rows carry the quality columns, `summary` counts
  the observations per quality byte and lists the quality levels, and the plot marks corrected,
  confirmed, doubtful and incorrect observations.
- `series()` has a `season_doy` column (day of the season, 1 = 1 January of the harvest year,
  negative for the autumn before) for comparing seasons, stations and crops on one axis.
- `plot_series()` – BBCH series of several stations, crops and seasons in one plot or as small
  multiples (`x="date"|"season_doy"`, `color_by="crop"|"station"|"season"`,
  `facet="station"|"crop"`); `plot_station()` is a shorthand for it.
- `plot_phase_trend()` – day of year of phases against year with OLS trend lines (days per
  decade in the legend). CLI: `dwdpheno plot --x --color-by --facet` with several station ids,
  and `dwdpheno plot-trend`.
- `places()` – search of the bundled German place list.
- On-disk cache (historical files never expire, everything else after `max_age_days`) and
  `offline=True`.
- `dwdpheno` command line tool with `stations crops phases download series summary places plot
  version` (CSV or JSON output).
