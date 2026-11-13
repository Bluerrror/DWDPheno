import os
import time

import pandas as pd
import pytest

import dwdpheno as dp
from dwdpheno import _catalog as catalog, _http
from dwdpheno._download import parse_years
from conftest import FIX

HIST = (f"{catalog.BASE_URL}/annual_reporters/crops/historical/"
        "PH_Jahresmelder_Landwirtschaft_Kulturpflanze_Winterweizen_1925_2024_hist.txt")
RECENT = (f"{catalog.BASE_URL}/annual_reporters/crops/recent/"
          "PH_Jahresmelder_Landwirtschaft_Kulturpflanze_Winterweizen_akt.txt")

EXPECTED_COLUMNS = [
    "station_id", "station_name", "latitude", "longitude", "elevation_m", "state", "county",
    "crop", "crop_de", "species", "objekt_id", "phase_id", "phase_name", "bbch_code",
    "year", "date", "day_of_year", "quality_byte", "quality_byte_meaning", "quality_level",
    "quality_level_meaning", "reporter", "partition", "source_file",
]


def test_parse_years():
    assert parse_years(None) is None
    assert parse_years(2005) == (2005, 2005, None)
    assert parse_years((2020, 2000)) == (2000, 2020, None)
    assert parse_years([1995, 1990]) == (1990, 1995, {1990, 1995})
    assert parse_years("2000-2020") == (2000, 2020, None)
    assert parse_years("1990,1995") == (1990, 1995, {1990, 1995})
    assert parse_years("2005") == (2005, 2005, None)


def test_download_tidy_columns(fake):
    obs = dp.download("winter wheat")
    assert list(obs.columns) == EXPECTED_COLUMNS == dp.OBS_COLUMNS
    assert len(obs) == 58 + 24
    assert set(obs["crop"]) == {"winter wheat"} and set(obs["crop_de"]) == {"Winterweizen"}
    assert set(obs["species"]) == {"Triticum aestivum"}
    r = obs[(obs.station_id == 15557) & (obs.year == 2024) & (obs.phase_id == 15)].iloc[0]
    assert r["date"] == pd.Timestamp("2024-04-16")
    assert r["day_of_year"] == 106
    assert r["bbch_code"] == "31" and r["phase_name"] == "beginning of shooting"
    assert r["objekt_id"] == 202 and r["elevation_m"] == 230
    harvest = obs[obs.phase_id == 24].iloc[0]
    assert harvest["phase_name"] == "harvest" and pd.isna(harvest["bbch_code"])
    assert r["quality_byte_meaning"] == "not flagged"
    assert r["quality_level"] == 10 and r["quality_level_meaning"] == "ROUTKLI checked + corrected"
    assert r["partition"] == "recent" and r["reporter"] == "annual"
    assert r["source_file"].endswith("_akt.txt")
    assert r["county"] == "Schwalm-Eder-Kreis" and r["state"] == "Hessen"
    assert obs.loc[obs.year == 2026, "quality_level_meaning"].eq("pre-load check only").all()
    key = ["crop", "station_id", "year", "date", "phase_id"]
    assert obs[key].equals(obs[key].sort_values(key, kind="stable").reset_index(drop=True))


def test_download_csv_dates_are_iso(fake, tmp_path):
    obs = dp.download("Winterweizen", years=2024)
    p = tmp_path / "o.csv"
    obs.to_csv(p, index=False)
    assert ",2024-04-16," in p.read_text(encoding="utf-8")


def test_recent_wins_over_historical(fake):
    raw = (FIX / HIST.rsplit("/", 1)[1]).read_bytes()
    extra = (b"       15557;          2024;             10;              202;             15;"
             b"       20240401;                1;     92;eor;\r\n")
    fake.extra[HIST] = raw + extra
    obs = dp.download("winter wheat", years=2024, station_id=15557)
    r = obs[obs.phase_id == 15]
    assert len(r) == 1
    assert r["date"].iloc[0] == pd.Timestamp("2024-04-16")
    assert r["partition"].iloc[0] == "recent"
    hist_only = dp.download("winter wheat", years=2024, station_id=15557, partition="historical")
    assert hist_only["date"].tolist() == [pd.Timestamp("2024-04-01")]


def test_years_and_station_filters(fake):
    obs = dp.download("winter wheat", years=(2018, 2019), station_id=15557)
    assert set(obs["year"]) == {2018, 2019} and set(obs["station_id"]) == {15557}
    obs = dp.download("winter wheat", years=[2016, 2025])
    assert set(obs["year"]) == {2016, 2025}
    fake.calls.clear()
    obs = dp.download("winter wheat", county="Schwalm-Eder-Kreis", partition="historical")
    assert set(obs["partition"]) == {"historical"}
    assert RECENT not in fake.calls


def test_no_match(fake):
    with pytest.raises(dp.NoMatchError):
        dp.download("banana")
    with pytest.raises(dp.NoMatchError):
        dp.download("winter wheat", name="nowhere-station")
    empty = dp.download("winter wheat", years=1950)        # file matches, no rows
    assert empty.empty and list(empty.columns) == dp.OBS_COLUMNS


def test_cache_and_offline(fake):
    dp.download("winter wheat")
    n = len(fake.calls)
    dp.download("winter wheat")
    assert len(fake.calls) == n                      # everything fresh in the cache
    obs = dp.download("winter wheat", offline=True)
    assert len(fake.calls) == n and len(obs) == 82
    # age the cache: listings / metadata / recent are re-fetched, historical files are not
    old = time.time() - 3 * 86400
    for f in _http.default_cache_dir().rglob("*"):
        if f.is_file():
            os.utime(f, (old, old))
    dp.download("winter wheat")
    again = fake.calls[n:]
    assert RECENT in again and HIST not in again


def test_offline_without_cache_fails(fake):
    with pytest.raises(dp.NetworkError):
        dp.stations(offline=True)


def test_cache_disabled(fake, tmp_path):
    dp.stations(cache=False)
    dp.stations(cache=False)
    assert not (tmp_path / "cache").exists()
    assert sum("Stationen_Jahresmelder" in u for u in fake.calls) == 2


def test_http_fails_fast_on_404(monkeypatch):
    import urllib.error
    calls = []

    def boom(req, timeout=None):
        calls.append(req.full_url)
        assert req.get_header("User-agent").startswith(f"dwdpheno/{dp.__version__}")
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr(_http.urllib.request, "urlopen", boom)
    with pytest.raises(dp.NetworkError) as e:
        _http._get("https://example.invalid/x")
    assert e.value.status == 404 and len(calls) == 1


def test_http_retries_server_errors(monkeypatch):
    import urllib.error
    calls = []

    def flaky(req, timeout=None):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 503, "Busy", {}, None)

    monkeypatch.setattr(_http.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(_http.time, "sleep", lambda s: None)
    with pytest.raises(dp.NetworkError):
        _http._get("https://example.invalid/x", retries=3)
    assert len(calls) == 3
