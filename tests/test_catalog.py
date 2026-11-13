import datetime

import pandas as pd

import dwdpheno as dp
from dwdpheno import _catalog as catalog
from conftest import FIX


def _fix(name):
    return (FIX / name).read_bytes()


def test_parse_listing():
    names = catalog.parse_listing(_fix("listing_annual_crops_recent.html"))
    assert "../" not in names
    assert "PH_Jahresmelder_Landwirtschaft_Kulturpflanze_Winterweizen_akt.txt" in names
    assert "PH_Beschreibung_Phasendefinition_Jahresmelder_Landwirtschaft_Kulturpflanze.txt" in names
    assert all(not n.endswith("/") for n in names)


def test_parse_data_filename():
    p = catalog.parse_data_filename
    assert p("PH_Jahresmelder_Landwirtschaft_Kulturpflanze_Winterweizen_1925_2024_hist.txt",
             "annual") == ("Landwirtschaft_Kulturpflanze", "Winterweizen", 1925, 2024)
    assert p("PH_Jahresmelder_Obst_Apfel_fruehe_Reife_1929_2018_hist.txt", "annual") == \
        ("Obst", "Apfel_fruehe_Reife", 1929, 2018)
    assert p("PH_Jahresmelder_Weinrebe_Weinrebe_fruehe_Reife_akt.txt", "annual") == \
        ("Weinrebe", "Weinrebe_fruehe_Reife", None, None)
    assert p("PH_Sofortmelder_Wein_Mueller-Thurgau_1990_2020_hist.txt", "immediate") == \
        ("Wein", "Mueller-Thurgau", 1990, 2020)
    # historical file without a year range: kept, years unknown
    assert p("PH_Sofortmelder_Landwirtschaft_Kulturpflanze_Ruebe_hist.txt", "immediate") == \
        ("Landwirtschaft_Kulturpflanze", "Ruebe", None, None)
    assert p("PH_Jahresmelder_Landwirtschaft_Kulturpflanze_Ruebe_Spezifizierung.txt", "annual") is None
    assert p("PH_Jahresmelder_Obst_Notiz.txt", "annual") is None
    assert p("PH_Beschreibung_Phaenologie_Besonderheiten_Zeitreihen.txt", "annual") is None
    assert p("PH_Jahresmelder_Obst_Apfel_akt.txt", "immediate") is None   # wrong infix


def test_read_table_records_and_eor():
    raw = ("a;b;eor;\r\n 1 ;Georgsmarienhütte ;eor;\r\n 2 ;two\r\nlines ;eor ;\r\n"
           " 3 ; ;eor;\r\n\x1a").encode("cp1252")
    t = catalog.read_table(raw)
    assert list(t.columns) == ["a", "b"]
    assert t["a"].tolist() == ["1", "2", "3"]
    assert t["b"].tolist() == ["Georgsmarienhütte", "two lines", None]


def test_parse_plants():
    pl = catalog.parse_plants(_fix("PH_Beschreibung_Pflanze.txt")).set_index("objekt_id")
    assert pl.loc[202, ["crop", "crop_de", "species"]].tolist() == \
        ["winter wheat", "Winterweizen", "Triticum aestivum"]
    assert pl.loc[25, "species"] == "Beta vulgaris"            # record spans two lines
    assert pl.loc[311, "crop"] == "apple (early ripeness)"
    assert pl.loc[250, "crop"] == "beet (variety unknown)"     # DWD calls 25 and 250 "beet"
    assert pl.loc[25, "crop"] == "beet"
    assert pd.isna(pl.loc[201, "species"])                     # "----------"
    assert pl.index.is_unique and len(pl) > 90


def test_parse_phase_names():
    ph = catalog.parse_phase_names(_fix("PH_Beschreibung_Phase.txt")).set_index("phase_id")
    assert ph.loc[15, "phase_name"] == "beginning of shooting"
    assert ph.loc[24, "phase_name"] == "harvest"
    assert ph.loc[15, "phase_name_de"] == "Schossen Beginn"


def test_plant_of_token():
    pl = catalog.parse_plants(_fix("PH_Beschreibung_Pflanze.txt"))
    f = catalog.plant_of_token
    assert f("Winterweizen", pl) == 202
    assert f("Apfel_fruehe_Reife", pl) == 311
    assert f("Birke_alleArten", pl) == 111
    assert f("Weinrebe_mittelspaete_Reife", pl) == 412
    assert f("Pflaume_fruehreifend", pl) == 371
    assert f("Zucker-Ruebe", pl) == 253
    assert f("Rueben_ohne_Sortenangabe", pl) == 250             # fixed exception
    assert f("Ruebe", pl) == 25
    assert f("Gibtsnicht", pl) is None


def test_latest_historical_version_wins(fake):
    files = catalog.data_files(["annual"], ["historical"], groups=["fruit"])
    early = [f for f in files if f.crop == "Apfel_fruehe_Reife"]
    assert len(early) == 1 and (early[0].y0, early[0].y1) == (1929, 2024)
    assert [f.y1 for f in files if f.crop == "Rote_Johannisbeere"] == [2024]
    assert len({f.crop for f in files}) == len(files)


def test_crops_catalog(fake):
    c = dp.crops()
    assert list(c.columns) == dp.CROP_COLUMNS
    assert c["dwd_token"].is_unique
    ww = c.set_index("dwd_token").loc["Winterweizen"]
    assert ww[["crop", "crop_de", "species", "objekt_id", "group", "reporters"]].tolist() == \
        ["winter wheat", "Winterweizen", "Triticum aestivum", 202, "crops", "annual"]
    this_year = datetime.date.today().year
    assert (ww["first_year"], ww["last_year"], ww["files"]) == (1925, this_year, 2)  # has recent
    early = c.set_index("dwd_token").loc["Apfel_fruehe_Reife"]
    assert early["crop"] == "apple (early ripeness)" and early["objekt_id"] == 311
    assert (early["first_year"], early["last_year"], early["files"]) == (1929, 2024, 1)
    ruebe = c.set_index("dwd_token").loc["Ruebe"]                 # only a recent file
    assert pd.isna(ruebe["first_year"]) and ruebe["last_year"] == this_year
    assert ruebe["crop"] == "beet"
    # sorted by group, then English name (case-insensitive)
    key = list(zip(c["group"], c["crop"].str.lower()))
    assert key == sorted(key)
    assert c["group"].tolist()[0] == "crops" and c["group"].tolist()[-1] == "fruit"


def test_select_crops(fake):
    cat = dp.crops()

    def sel(*q):
        return sorted(catalog.select_crops(list(q), cat)["dwd_token"])

    assert sel("apple") == ["Apfel"]                                   # exact English name
    assert sel("Apfel") == ["Apfel"]                                   # exact German name
    assert sel("Apfel_fruehe_Reife") == ["Apfel_fruehe_Reife"]         # exact token
    assert sel("apple early") == ["Apfel_fruehe_Reife"]
    assert sel("app") == ["Apfel", "Apfel_fruehe_Reife", "Apfel_spaete_Reife"]
    assert sel("wheat") == ["Sommerweizen", "Winterweizen"]
    assert sel("winter wheat", "maize") == ["Mais", "Winterweizen"]
    assert sel("Zucker-Rübe") == ["Zucker-Ruebe"]
    assert sel("banana") == []


def test_phases(fake):
    ph = dp.phases()
    assert list(ph.columns) == dp.PHASE_COLUMNS == ["objekt_id", "crop", "phase_id",
                                                     "phase_name", "bbch_code"]
    assert not ph.duplicated(["objekt_id", "phase_id"]).any()
    ww = dp.phases("winter wheat")
    assert set(ww["objekt_id"]) == {202} and set(ww["crop"]) == {"winter wheat"}
    got = dict(zip(ww["phase_id"], zip(ww["phase_name"], ww["bbch_code"])))
    assert got[10] == ("beginning of tilling sowing drilling", "0")
    assert got[15] == ("beginning of shooting", "31")
    assert got[21][1] == "87"
    assert got[24][0] == "harvest" and pd.isna(got[24][1])       # no BBCH code
    mais = dp.phases("maize")
    assert set(mais["objekt_id"]) == {215} and mais["phase_id"].is_unique


def test_find_bbch(fake):
    rows = dp.find_bbch(15)
    assert 202 in set(rows["objekt_id"])
    assert dp.bbch_for(18, 202) == "51"
    assert dp.bbch_for(24, 202) is None
    assert dp.bbch_for(999, 202) is None
