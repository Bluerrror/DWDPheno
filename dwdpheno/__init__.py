"""dwdpheno - download plant-phenology observations of the German Weather Service (DWD).

Quick start::

    import dwdpheno as dp

    st = dp.stations(county="Kassel rural district")
    obs = dp.download("winter wheat", years=(2015, 2024), county="Kassel rural district")
    curves = dp.series(obs)
    stats = dp.summary(obs)
    dp.plot_station(obs, station_id=obs.station_id.iloc[0])

Data: Deutscher Wetterdienst (DWD) Climate Data Center, CC BY 4.0.
"""
__version__ = "1.0.0"

from ._http import DWDPhenoError, NetworkError, NoMatchError, default_cache_dir
from ._text import fold, matches
from ._catalog import CROP_COLUMNS, PHASE_COLUMNS, bbch_for, crops, find_bbch, phases
from ._download import OBS_COLUMNS, QUALITY_BYTE, QUALITY_LEVEL, download
from ._plot import plot_phase_trend, plot_series, plot_station
from ._series import BBCH_PRINCIPAL_STAGES, SERIES_COLUMNS, SUMMARY_COLUMNS, pchip, series, summary
from ._stations import STATION_COLUMNS, assign_counties, places, select_stations, stations

__all__ = [
    "__version__", "stations", "select_stations", "places", "crops", "phases", "download",
    "series", "summary", "plot_series", "plot_station", "plot_phase_trend", "find_bbch", "bbch_for", "fold", "matches",
    "assign_counties", "pchip", "default_cache_dir", "QUALITY_BYTE", "QUALITY_LEVEL",
    "BBCH_PRINCIPAL_STAGES", "STATION_COLUMNS", "CROP_COLUMNS", "PHASE_COLUMNS", "OBS_COLUMNS",
    "SERIES_COLUMNS", "SUMMARY_COLUMNS", "DWDPhenoError", "NoMatchError", "NetworkError",
]
