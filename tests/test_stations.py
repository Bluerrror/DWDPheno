import numpy as np
import pandas as pd
import pytest

import dwdpheno as dp
from dwdpheno import _stations as st_mod
from conftest import FIX


def test_parse_stations_windows1252():
    df = st_mod.parse_stations(
        (FIX / "PH_Beschreibung_Phaenologie_Stationen_Jahresmelder.txt").read_bytes())
    names = dict(zip(df["station_id"], df["station_name"]))
    assert names[7503] == "Kiel-Düsternbrook"
    assert names[7507] == "Lübeck-Sankt Jürgen"
    assert names[7501] == "Flensburg, kreisfreie Stadt Flensburg"   # comma inside a field
    assert df["naturraumgruppe"].iloc[0] == "Schleswig-Holsteinisches Hügelland"
    assert df["station_id"].dtype == np.int64
    assert df.loc[df.station_id == 15557, "latitude"].item() == pytest.approx(51.1781)


def test_station_table_columns_and_reporter(fake):
    t = dp.stations()
    assert list(t.columns) == dp.STATION_COLUMNS
    assert t["station_id"].is_unique and t["station_id"].is_monotonic_increasing
    rep = dict(zip(t["station_id"], t["reporter"]))
    assert rep[7501] == "annual"      # only in Jahresmelder
    assert rep[7502] == "both"        # in both files
    assert rep[7525] == "immediate"   # only in Sofortmelder
    act = dict(zip(t["station_id"], t["active_until"]))
    assert act[7501] == "31.12.1999" and pd.isna(act[15557])


def test_counties_and_nearest_place(fake):
    t = dp.stations().set_index("station_id")
    assert t.loc[7501, ["county", "county_type", "county_id"]].tolist() == \
        ["Flensburg", "urban district", "01001"]
    assert t.loc[7503, "county"] == "Kiel"
    assert t.loc[15557, "county"] == "Schwalm-Eder-Kreis"
    assert t.loc[15557, "nearest_place"] == "Gudensberg"
    assert t.loc[15557, "nearest_place_km"] == 0.13           # 2 decimals
    assert t.loc[15557, "elevation_m"] == 230 and str(t["elevation_m"].dtype) == "Int64"
    assert t.loc[15557, "latitude"] == 51.1781


def test_assign_counties_kassel_area():
    c = dp.assign_counties([51.3127, 51.2560, 52.0, 47.0], [9.4797, 9.4181, 2.0, 0.0])
    assert c.loc[0, ["county", "county_type", "county_id"]].tolist() == \
        ["Kassel", "urban district", "06611"]            # Kassel city centre
    assert c.loc[1, ["county", "county_type", "county_id"]].tolist() == \
        ["Kassel", "rural district", "06633"]            # Baunatal
    assert c.loc[2:3, "county"].isna().all()             # outside Germany


def test_even_odd_hole():
    outer = np.array([[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]], float)
    hole = np.array([[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]], float)
    px = np.array([1.0, 5.0, 11.0])
    py = np.array([1.0, 5.0, 5.0])
    assert st_mod._even_odd(px, py, [outer, hole]).tolist() == [True, False, False]


def test_select_station_id(fake):
    assert dp.stations(station_id=15557)["station_id"].tolist() == [15557]
    assert dp.stations(station_id="7502,7501")["station_id"].tolist() == [7501, 7502]
    assert dp.stations(station_id=[19402, 15557])["station_id"].tolist() == [15557, 19402]


def test_select_name(fake):
    assert dp.stations(name="kiel")["station_id"].tolist() == [7502, 7503, 7504]
    assert dp.stations(name="Duesternbrook")["station_id"].tolist() == [7503]
    assert dp.stations(name="Kiel-Pries,Gudensberg")["station_id"].tolist() == [7502, 15557]
    assert dp.stations(name=["luebeck sankt"])["station_id"].tolist() == [7506, 7507]


def test_select_state_and_county(fake):
    assert dp.stations(state="hessen")["station_id"].tolist() == [15557, 19402]
    assert dp.stations(county="Schwalm-Eder")["station_id"].tolist() == [15557, 19402]
    assert dp.stations(county="Landkreis Schwalm Eder")["station_id"].tolist() == [15557, 19402]
    assert dp.stations(county="Schwalm-Eder rural district")["station_id"].tolist() == [15557, 19402]
    assert dp.stations(county="Kiel urban district")["station_id"].tolist() == [7502, 7503, 7504]
    assert dp.stations(county="Kiel Kreisfreie Stadt")["station_id"].tolist() == [7502, 7503, 7504]
    assert dp.stations(county="Landkreis Kiel").empty
    assert dp.stations(county="Kiel rural district").empty


def test_select_radius_and_nearest(fake):
    r = dp.stations(lat=51.18, lon=9.37, radius_km=5)
    assert r["station_id"].tolist() == [15557]
    assert list(r.columns) == dp.STATION_COLUMNS + ["distance_km"]
    assert r["distance_km"].iloc[0] < 1
    d = dp.stations(lat=51.18, lon=9.37)          # default radius 25 km
    assert d["station_id"].tolist() == [15557, 19402]
    assert d["distance_km"].is_monotonic_increasing
    n = dp.stations(lat=54.33, lon=10.13, nearest=2)
    assert n["station_id"].tolist() == [7503, 7504]


def test_select_city(fake):
    r = dp.stations(city="Kassel", radius_km=30)
    assert r["station_id"].tolist() == [15557, 19402]
    assert dp.stations(city="Kiel", nearest=1)["station_id"].tolist() == [7503]
    with pytest.raises(dp.NoMatchError):
        dp.stations(city="Atlantis")


def test_select_bbox_polygon(fake):
    b = dp.stations(bbox=(51.0, 9.0, 51.5, 9.5))
    assert b["station_id"].tolist() == [15557, 19402]
    assert dp.stations(bbox="51.0,9.3,51.5,9.5")["station_id"].tolist() == [15557]
    poly = [(51.0, 9.3), (51.3, 9.3), (51.3, 9.5), (51.0, 9.5)]
    assert dp.stations(polygon=poly)["station_id"].tolist() == [15557]
    assert dp.stations(polygon="51.0 9.3;51.3 9.3;51.3 9.5;51.0 9.5")["station_id"].tolist() == [15557]


def test_select_reporter_active_and(fake):
    imm = dp.stations(reporter="immediate")
    assert set(imm["reporter"]) <= {"immediate", "both"} and 7525 in set(imm["station_id"])
    ann = dp.stations(reporter="annual")
    assert 7525 not in set(ann["station_id"]) and 7502 in set(ann["station_id"])
    act = dp.stations(active=True)
    assert act["station_id"].tolist() == [7532, 15557, 19402]
    assert dp.stations(active=True, state="Schleswig")["station_id"].tolist() == [7532]


def test_selection_errors(fake):
    with pytest.raises(ValueError):
        dp.stations(lat=51.0)
    with pytest.raises(ValueError):
        dp.stations(radius_km=10)
    with pytest.raises(ValueError):
        dp.stations(reporter="weekly")


def test_places():
    p = dp.places("Göttingen")
    assert list(p.columns) == ["name", "latitude", "longitude", "population", "state"]
    assert p.iloc[0]["name"] == "Göttingen"
    k = dp.places("kassel")
    assert k.iloc[0]["name"] == "Kassel"
    assert len(dp.places("berlin", limit=1)) == 1
    assert dp.places("xyzzy-nowhere").empty


def test_stations_with_crops(fake):
    obs = dp.download("winter wheat")
    want = obs.groupby("station_id")["year"].agg(["size", "min", "max"])
    st = dp.stations(crops="winter wheat")
    assert list(st.columns) == dp.STATION_COLUMNS + ["n_observations", "first_year", "last_year"]
    assert st["station_id"].tolist() == [15557, 19402]          # only stations with data
    for _, r in st.iterrows():
        w = want.loc[r["station_id"]]
        assert (r["n_observations"], r["first_year"], r["last_year"]) == \
            (w["size"], w["min"], w["max"])
    yr = dp.stations(crops="winter wheat", years=(2024, 2025)).set_index("station_id")
    assert yr.loc[19402, ["n_observations", "first_year", "last_year"]].tolist() == [3, 2024, 2025]
    assert dp.stations(crops="winter wheat", years=2016)["station_id"].tolist() == [15557]
    near = dp.stations(crops="winter wheat", lat=51.18, lon=9.37)   # keeps distance + sort
    assert near["station_id"].tolist() == [15557, 19402] and "distance_km" in near.columns
    assert list(near.columns)[-4:] == ["distance_km", "n_observations", "first_year", "last_year"]
    assert dp.stations(crops="winter wheat", quality=[2]).empty      # nothing corrected
    assert dp.stations(crops="winter wheat", partition="recent", years=2016).empty
    none = dp.stations(crops="winter wheat", name="Kiel")            # selection without data
    assert none.empty and "n_observations" in none.columns
    with pytest.raises(dp.NoMatchError):
        dp.stations(crops="banana")
    with pytest.raises(ValueError):
        dp.stations(years=2016)                                     # years need crops
