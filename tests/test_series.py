import numpy as np
import pandas as pd
import pytest

import dwdpheno as dp
from dwdpheno._series import pchip, split_cycles


def test_pchip_monotone_no_overshoot():
    x = np.array([0.0, 10, 12, 40, 41, 90, 120])
    y = np.array([0.0, 10, 31, 51, 75, 87, 87])
    xi = np.linspace(0, 120, 2001)
    yi = pchip(x, y, xi)
    assert np.all(np.diff(yi) >= -1e-9)                    # monotone data -> monotone curve
    assert yi.min() >= -1e-9 and yi.max() <= 87 + 1e-9     # no overshoot
    assert np.allclose(pchip(x, y, x), y)                  # passes through the nodes
    assert np.allclose(pchip(x, y, np.linspace(90, 120, 7)), 87)   # flat stays flat


def test_pchip_local_extremum_and_two_points():
    x = np.array([0.0, 1, 2, 3])
    y = np.array([0.0, 5, 3, 4])
    yi = pchip(x, y, np.linspace(0, 3, 301))
    assert yi.max() <= 5 + 1e-9 and yi.min() >= -1e-9
    assert np.allclose(pchip([0, 2], [0, 10], [0, 1, 2]), [0, 5, 10])


def test_split_cycles():
    t = np.array([0, 10, 180, 220, 250, 280, 291.0])
    b = np.array([0, 10, 31, 51, 87, 0, 10.0])
    assert split_cycles(t, b).tolist() == [0, 0, 0, 0, 0, 1, 1]
    assert split_cycles(np.array([0, 10, 400.0]), np.array([31, 51, 75.0])).tolist() == [0, 0, 1]
    assert split_cycles(np.array([0, 5.0]), np.array([60, 45.0])).tolist() == [0, 0]  # drop <= 20


def test_series_seasons_from_data(fake):
    obs = dp.download("winter wheat", station_id=15557)
    s = dp.series(obs)
    assert list(s.columns) == dp.SERIES_COLUMNS
    pts = s[s.kind == "point"]
    # Referenzjahr 2024 holds April-2024 stages *and* the October-2024 sowing (-> season 2025)
    sow = pts[pts.date == pd.Timestamp("2024-10-07")]
    assert sow["season"].tolist() == [2025] and sow["bbch"].tolist() == [0.0]
    assert pts.loc[pts.date == pd.Timestamp("2024-04-16"), "season"].tolist() == [2024]
    s24 = pts[pts.season == 2024].sort_values("t")
    assert s24["date"].iloc[0] == pd.Timestamp("2023-10-14")     # sown in autumn 2023
    assert s24["bbch"].tolist() == [0, 10, 31, 51, 75, 87]
    assert 24 not in set(pts["phase_id"].dropna())               # harvest has no BBCH code
    t0 = (pd.Timestamp("2023-10-14") - pd.Timestamp("1970-01-01")).days
    assert s24["t"].iloc[0] == t0
    cur = s[(s.kind == "curve") & (s.season == 2024)]
    assert cur["t"].iloc[0] == s24["t"].iloc[0] and cur["t"].iloc[-1] == s24["t"].iloc[-1]
    assert np.allclose(np.diff(cur["t"]), 1.0)
    assert np.all(np.diff(cur["bbch"].to_numpy()) >= -1e-9)
    assert cur["bbch"].between(0, 87).all()
    assert (cur["bbch"] == cur["bbch"].round(2)).all()
    assert cur["phase_id"].isna().all()
    assert (cur["date"] == pd.to_datetime("1970-01-01") + pd.to_timedelta(cur["t"], "D")).all()


def test_series_step_and_filters(fake):
    obs = dp.download("winter wheat")
    s = dp.series(obs, station_id=15557, crops="winter wheat", step_days=7)
    cur = s[(s.kind == "curve") & (s.season == 2024)]
    d = np.diff(cur["t"].to_numpy())
    assert np.allclose(d[:-1], 7) and 0 < d[-1] <= 7
    assert set(s["station_id"]) == {15557}
    assert dp.series(obs, crops="maize").empty


def test_series_keeps_quality_8_unless_filtered():
    obs = pd.DataFrame({
        "station_id": [1, 1, 1], "crop": ["X"] * 3, "bbch_code": ["10", "31", "51"],
        "date": pd.to_datetime(["2020-04-01", "2020-05-01", "2020-06-01"]),
        "quality_byte": [1, 8, 8], "phase_id": [1, 2, 3], "phase_name": ["a", "b", "c"]})
    s = dp.series(obs)                                          # default: nothing dropped
    assert (s.kind == "point").sum() == 3 and (s.kind == "curve").sum() == 62
    assert dp.series(obs, quality=[1])["kind"].tolist() == ["point"]   # single point, no curve


def test_series_merges_identical_dates_for_curve():
    obs = pd.DataFrame({
        "station_id": 1, "crop": "X", "bbch_code": ["10", "20", "31"],
        "date": pd.to_datetime(["2020-04-01", "2020-04-01", "2020-04-11"]),
        "quality_byte": 1, "phase_id": [1, 2, 3], "phase_name": ["a", "b", "c"]})
    s = dp.series(obs)
    assert (s.kind == "point").sum() == 3
    cur = s[s.kind == "curve"]
    assert len(cur) == 11 and cur["bbch"].iloc[0] == 20 and cur["bbch"].iloc[-1] == 31


def test_summary_trend():
    years = np.arange(2000, 2010)
    doy = 120 - 0.5 * (years - 2000)                       # 5 days earlier per decade
    obs = pd.DataFrame({"station_id": 1, "crop": "Apfel", "objekt_id": 310, "phase_id": 5,
                        "phase_name": "Blüte Beginn", "bbch_code": "60", "year": years,
                        "day_of_year": doy})
    two = obs.head(2).assign(phase_id=6)
    out = dp.summary(pd.concat([obs, two]))
    assert list(out.columns) == dp.SUMMARY_COLUMNS
    r = out[out.phase_id == 5].iloc[0]
    assert r["n"] == 10 and r["first_year"] == 2000 and r["last_year"] == 2009
    assert r["trend_days_per_decade"] == -5.0
    assert r["mean_doy"] == round(doy.mean(), 2)
    assert r["sd_doy"] == round(np.std(doy, ddof=1), 2) == 1.51
    assert pd.isna(out[out.phase_id == 6].iloc[0]["trend_days_per_decade"])   # n < 3


def test_summary_on_fixture(fake):
    out = dp.summary(dp.download("winter wheat"))
    r = out[(out.station_id == 15557) & (out.phase_id == 15)].iloc[0]
    assert r["n"] == 11 and r["bbch_code"] == "31"
    assert r["min_doy"] == 96 and r["max_doy"] == 123


def test_unfinished_cycle_gets_next_season(fake):
    mpl = pytest.importorskip("matplotlib")
    mpl.use("Agg")
    # Referenzjahr 2024 only: Apr-Jul 2024 stages + the Oct-2024 sowing, whose last point is
    # also in 2024 -> previous season + 1
    obs = dp.download("winter wheat", years=2024, station_id=15557)
    s = dp.series(obs)
    pts = s[s.kind == "point"]
    assert pts.loc[pts.date < pd.Timestamp("2024-08-01"), "season"].unique().tolist() == [2024]
    assert pts.loc[pts.date > pd.Timestamp("2024-08-01"), "season"].unique().tolist() == [2025]
    ax = dp.plot_station(obs, 15557)
    drawn = [ln for ln in ax.lines if ln.get_linestyle() == "-"]
    assert len(drawn) == 2                                      # one curve per cycle


def test_fixture_last_sowing_gets_next_season(fake):
    s = dp.series(dp.download("winter wheat", station_id=15557))
    pts = s[s.kind == "point"]
    last = pts[pts.date >= pd.Timestamp("2026-10-01")]          # sown Oct 2026, no 2027 data
    assert last["season"].unique().tolist() == [2027]
    assert pts.groupby("season").size().index.is_unique


def test_plot_station(fake, tmp_path):
    mpl = pytest.importorskip("matplotlib")
    mpl.use("Agg")
    obs = dp.download("winter wheat")
    ax = dp.plot_station(obs, 15557, years=(2020, 2024))
    assert ax.get_yticks().tolist() == list(range(0, 100, 10))
    assert "Gudensberg" in ax.get_title()
    ax.figure.savefig(tmp_path / "p.png")
    assert (tmp_path / "p.png").stat().st_size > 1000
