"""season_doy, plot_series (overlay / colour / style / facets), plot_phase_trend, plot CLI."""
import numpy as np
import pandas as pd
import pytest

import dwdpheno as dp
from dwdpheno.cli import main

mpl = pytest.importorskip("matplotlib")
mpl.use("Agg")


@pytest.fixture
def obs(fake):
    return dp.download("winter wheat")


def _solid_lines(ax):
    return [ln for ln in ax.lines if ln.get_linestyle() not in ("None", "") and len(ln.get_xdata())]


def test_season_doy(obs):
    s = dp.series(obs)
    assert list(s.columns)[5:8] == ["t", "season_doy", "bbch"]
    jan1 = (pd.to_datetime(s["season"].astype(str) + "-01-01") - pd.Timestamp("1970-01-01")).dt.days
    assert np.allclose(s["season_doy"], s["t"] - jan1 + 1)
    sow = s[(s.kind == "point") & (s.date == pd.Timestamp("2024-10-07"))].iloc[0]
    assert sow["season"] == 2025 and sow["season_doy"] == -85.0      # 7 Oct 2024 -> -85
    synthetic = pd.DataFrame({"station_id": 1, "crop": "X", "bbch_code": ["0", "87"],
                              "date": pd.to_datetime(["2000-10-06", "2001-07-01"])})
    assert dp.series(synthetic).query("kind == 'point'")["season_doy"].tolist() == [-86.0, 182.0]
    apr = s[(s.kind == "point") & (s.date == pd.Timestamp("2024-04-16"))].iloc[0]
    assert apr["season_doy"] == 107.0
    assert (s["season_doy"] == s["season_doy"].round(2)).all()


def test_series_lists_of_stations_and_crops(obs):
    s = dp.series(obs, station_id=[15557, 19402], crops=["winter wheat"])
    assert set(s["station_id"]) == {15557, 19402}


def test_plot_series_overlay_by_station(obs):
    ax = dp.plot_series(obs, station_id=[15557, 19402], x="season_doy", color_by="station",
                        years=(2024, 2025))
    legends = [t.get_text() for leg in ax.findobj(mpl.legend.Legend) for t in leg.get_texts()]
    assert "Gudensberg (Ph) (15557)" in legends and "Ungedanken (19402)" in legends
    assert ax.get_xlabel().startswith("day of season")
    ticks = [t.get_text() for t in ax.get_xticklabels()]
    assert {"Nov", "Jan", "Jul"} <= set(ticks)
    lo, hi = ax.get_xlim()
    assert lo < -60 and hi > 200                                       # autumn before .. summer
    colours = {ln.get_color() for ln in _solid_lines(ax)}
    assert len(colours) == 2                                           # one colour per station


def test_plot_series_colour_by_season_style_by_station(obs):
    ax = dp.plot_series(obs, x="season_doy", color_by="season", years=(2023, 2025))
    legends = [t.get_text() for leg in ax.findobj(mpl.legend.Legend) for t in leg.get_texts()]
    assert {"2023", "2024", "2025"} <= set(legends)                  # colour = season
    assert "Gudensberg (Ph) (15557)" in legends                       # line style = station
    assert ax.get_title() == "winter wheat"


def test_plot_series_facets(obs):
    axes = dp.plot_series(obs, x="season_doy", color_by="season", facet="station",
                          years=(2024, 2025))
    assert isinstance(axes, list) and len(axes) == 2
    assert [a.get_title() for a in axes] == ["Gudensberg (Ph) (15557)", "Ungedanken (19402)"]
    assert axes[0].get_shared_x_axes().joined(axes[0], axes[1])
    assert axes[0].get_shared_y_axes().joined(axes[0], axes[1])


def test_plot_series_date_axis_and_errors(obs):
    ax = dp.plot_series(obs, station_id=15557, years=2024)
    assert "Gudensberg" in ax.get_title()
    with pytest.raises(ValueError):
        dp.plot_series(obs, x="doy")
    with pytest.raises(ValueError):
        dp.plot_series(obs, color_by="station", facet="station")
    with pytest.raises(dp.NoMatchError):
        dp.plot_series(obs, years=1900)


def test_plot_station_is_a_wrapper(obs):
    a = dp.plot_station(obs, 15557, years=(2020, 2024))
    b = dp.plot_series(obs, station_id=15557, years=(2020, 2024), x="date", color_by="crop")
    assert len(a.lines) == len(b.lines)


def test_plot_phase_trend(obs):
    one = obs[obs.station_id == 15557]
    ax = dp.plot_phase_trend(one, phases=["beginning of shooting", 24])
    labels = [t.get_text() for t in ax.get_legend().get_texts()]
    assert len(labels) == 2 and all("d/decade" in t for t in labels)
    trend = dp.summary(one).set_index("phase_id").loc[15, "trend_days_per_decade"]
    assert any(t.startswith("beginning of shooting:") and f"{trend:+.1f} d/decade" in t
               for t in labels)                                         # same as summary()
    assert "Gudensberg" in ax.get_title()
    ax = dp.plot_phase_trend(obs, phases="heading")                     # word prefix, 2 stations
    assert "2 stations" in ax.get_title()
    assert [t.get_text() for t in ax.get_legend().get_texts()][0].startswith("beginning of heading")
    with pytest.raises(dp.NoMatchError):
        dp.plot_phase_trend(obs, phases="flowering")


def test_cli_plot_and_trend(obs, tmp_path):
    f = tmp_path / "obs.csv"
    obs.to_csv(f, index=False)
    png = tmp_path / "multi.png"
    assert main(["plot", "--in", str(f), "--station-id", "15557,19402", "--x", "season_doy",
                 "--color-by", "station", "--years", "2023-2025", "--out", str(png)]) == 0
    assert png.stat().st_size > 1000
    png = tmp_path / "facet.png"
    assert main(["plot", "--in", str(f), "--color-by", "season", "--facet", "station",
                 "--x", "season_doy", "--out", str(png)]) == 0
    assert png.stat().st_size > 1000
    png = tmp_path / "trend.png"
    assert main(["plot-trend", "--in", str(f), "--phases", "15,18,harvest", "--station-id",
                 "15557", "--out", str(png)]) == 0
    assert png.stat().st_size > 1000
    assert main(["plot", "--in", str(f), "--years", "1900", "--out", str(png)]) == 2
    assert main(["plot", "--in", str(f), "--x", "doy", "--out", str(png)]) == 1
