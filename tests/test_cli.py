import datetime
import json

import pandas as pd
import pytest

import dwdpheno as dp
from dwdpheno.cli import main


def test_version(capsys):
    assert main(["version"]) == 0
    assert capsys.readouterr().out.strip() == dp.__version__


def test_stations_csv_json(fake, tmp_path, capsys):
    out = tmp_path / "st.csv"
    assert main(["stations", "--state", "Hessen", "--out", str(out), "--quiet"]) == 0
    df = pd.read_csv(out, dtype={"county_id": str})
    assert list(df.columns) == dp.STATION_COLUMNS
    assert df["station_id"].tolist() == [15557, 19402] and df["county_id"].tolist() == ["06634"] * 2
    line = out.read_text(encoding="utf-8").splitlines()[1]
    assert line.startswith("15557,Gudensberg (Ph),51.1781,9.3682,230,Hessen,Schwalm-Eder-Kreis,"
                           "rural district,06634,Gudensberg,0.13,")
    assert main(["stations", "--city", "Kassel", "--nearest", "1", "--format", "json"]) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["station_id"] == 15557 and isinstance(rows[0]["distance_km"], float)
    assert rows[0]["active_until"] is None


def test_download_series_summary_plot(fake, tmp_path, capsys):
    obs = tmp_path / "obs.csv"
    rc = main(["download", "--crops", "winter wheat", "--years", "2016-2025", "--county",
               "Schwalm-Eder", "--out", str(obs)])
    assert rc == 0
    assert "PROGRESS 1 2 " in capsys.readouterr().err
    df = pd.read_csv(obs)
    assert list(df.columns) == dp.OBS_COLUMNS and df["year"].between(2016, 2025).all()
    assert df["date"].str.match(r"^\d{4}-\d{2}-\d{2}$").all()

    ser = tmp_path / "ser.json"
    assert main(["series", "--in", str(obs), "--station-id", "15557", "--format", "json",
                 "--out", str(ser)]) == 0
    rows = json.loads(ser.read_text(encoding="utf-8"))
    assert {r["kind"] for r in rows} == {"point", "curve"}
    assert all(r["phase_id"] is None for r in rows if r["kind"] == "curve")
    sow = [r for r in rows if r["kind"] == "point" and r["date"] == "2024-10-07"]
    assert sow[0]["season"] == 2025

    summ = tmp_path / "sum.csv"
    assert main(["summary", "--in", str(obs), "--out", str(summ)]) == 0
    assert list(pd.read_csv(summ).columns) == dp.SUMMARY_COLUMNS

    pytest.importorskip("matplotlib")
    png = tmp_path / "p.png"
    assert main(["plot", "--in", str(obs), "--station-id", "15557", "--out", str(png)]) == 0
    assert png.stat().st_size > 1000


def test_crops_phases_places(fake, capsys):
    assert main(["crops", "--quiet"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == ",".join(dp.CROP_COLUMNS)
    y = datetime.date.today().year
    assert (f"winter wheat,Winterweizen,Triticum aestivum,202,Winterweizen,crops,annual,1925,{y},2"
            in out)
    assert f"beet,Rüben,Beta vulgaris,25,Ruebe,crops,annual,,{y},1" in out
    assert "apple (early ripeness),Apfel| frühe Reife".replace("|", ",") not in out  # quoted
    assert '"Apfel, frühe Reife"' in out
    assert main(["phases", "--crops", "winter wheat"]) == 0
    assert "202,winter wheat,15,beginning of shooting,31" in capsys.readouterr().out
    assert main(["places", "--q", "Göttingen", "--limit", "1"]) == 0
    assert capsys.readouterr().out.splitlines()[1].startswith("Göttingen,")


def test_exit_codes(fake, capsys):
    assert main([]) == 1
    assert main(["download"]) == 1                                  # --crops missing
    assert main(["download", "--crops", "banana"]) == 2
    assert main(["stations", "--name", "nowhere"]) == 2
    assert main(["stations", "--offline", "--cache", "off"]) == 3
    assert "ERROR " in capsys.readouterr().err


def test_global_options_before_command(fake, tmp_path, capsys):
    assert main(["--quiet", "--cache", str(tmp_path / "c2"), "stations", "--station-id",
                 "15557"]) == 0
    assert (tmp_path / "c2").exists()
    assert capsys.readouterr().out.splitlines()[1].startswith("15557,Gudensberg (Ph)")


def test_stations_with_crops_cli(fake, tmp_path):
    out = tmp_path / "st.csv"
    assert main(["stations", "--crops", "winter wheat", "--years", "2024-2025", "--quiet",
                 "--out", str(out)]) == 0
    df = pd.read_csv(out)
    assert df[["station_id", "n_observations", "first_year", "last_year"]].values.tolist() ==         [[15557, 14, 2024, 2025], [19402, 3, 2024, 2025]]
    assert main(["stations", "--crops", "winter wheat", "--name", "Kiel", "--quiet"]) == 2
