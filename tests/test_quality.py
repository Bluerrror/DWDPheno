"""Data-quality options: quality bytes / quality levels in download, series, summary, plot, CLI."""
import re

import pandas as pd
import pytest

import dwdpheno as dp
from dwdpheno._quality import filter_quality, parse_codes, QUALITY_BYTE
from dwdpheno.cli import main
from conftest import FIX
from test_download import HIST, RECENT

# 15557, Referenzjahr 2025: phase -> quality byte ("" = no byte)
QB_2025 = {15: "8", 18: "5", 19: "2", 21: "3", 24: ""}


def _with_quality(raw: bytes, year: int, qbs: dict) -> bytes:
    lines = raw.decode("cp1252").split("\r\n")
    out = []
    for ln in lines:
        f = ln.split(";")
        if len(f) > 8 and f[0].strip() == "15557" and f[1].strip() == str(year):
            pid = int(f[4])
            if pid in qbs:
                f[6] = qbs[pid].rjust(len(f[6]))
        out.append(";".join(f))
    return "\r\n".join(out).encode("cp1252")


@pytest.fixture
def mixed(fake):
    """Recent winter-wheat file with quality bytes 8, 5, 2, 3 and a missing byte in 2025."""
    raw = (FIX / RECENT.rsplit("/", 1)[1]).read_bytes()
    fake.extra[RECENT] = _with_quality(raw, 2025, QB_2025)
    return fake


def test_parse_codes():
    assert parse_codes(None, QUALITY_BYTE, "q") is None
    assert parse_codes("3,1,2", QUALITY_BYTE, "q") == [1, 2, 3]
    assert parse_codes(8, QUALITY_BYTE, "q") == [8]
    with pytest.raises(ValueError):
        parse_codes([4], QUALITY_BYTE, "q")
    with pytest.raises(ValueError):
        parse_codes("x", QUALITY_BYTE, "q")


def test_filter_missing_byte_counts_as_zero():
    df = pd.DataFrame({"quality_byte": [1, None, 8, 0], "quality_level": [10, 7, 1, 10]})
    assert filter_quality(df).index.tolist() == [0, 1, 2, 3]            # default: keep all
    assert filter_quality(df, quality=0).index.tolist() == [1, 3]
    assert filter_quality(df, quality=[1, 2, 3]).index.tolist() == [0]
    assert filter_quality(df, quality_level="7,10").index.tolist() == [0, 1, 3]
    assert filter_quality(df, quality=[0, 1], quality_level=10).index.tolist() == [0, 3]


def test_download_default_keeps_everything(mixed):
    obs = dp.download("winter wheat", years=2025, station_id=15557)
    got = dict(zip(obs["phase_id"], obs["quality_byte"]))
    assert got[15] == 8 and got[18] == 5 and got[19] == 2 and got[21] == 3 and pd.isna(got[24])
    m = dict(zip(obs["phase_id"], obs["quality_byte_meaning"]))
    assert m[15] == "incorrect" and m[18] == "doubtful" and m[21] == "confirmed despite flag"


def test_download_quality_filters(mixed):
    q = dp.download("winter wheat", years=2025, station_id=15557, quality=[1, 2, 3])
    assert sorted(q["quality_byte"].unique()) == [1, 2, 3]
    assert set(q["phase_id"]) == {10, 12, 19, 21}
    assert dp.download("winter wheat", years=2025, station_id=15557, quality=0)[
        "phase_id"].tolist() == [24]                                     # missing byte = 0
    lv = dp.download("winter wheat", station_id=15557, quality_level=[1])
    assert set(lv["year"]) == {2026} and set(lv["quality_level"]) == {1}
    with pytest.raises(ValueError):
        dp.download("winter wheat", quality=[4])


def test_recent_wins_before_quality_filter(fake):
    hist = (FIX / HIST.rsplit("/", 1)[1]).read_bytes()
    fake.extra[HIST] = hist + (b"       15557;          2024;             10;              202;"
                               b"             15;       20240401;                1;     92;eor;\r\n")
    recent = (FIX / RECENT.rsplit("/", 1)[1]).read_bytes()
    fake.extra[RECENT] = _with_quality(recent, 2024, {15: "8"})
    obs = dp.download("winter wheat", years=2024, station_id=15557, quality=[1])
    assert 15 not in set(obs["phase_id"])      # the recent row won, then was filtered out


def test_series_quality(mixed):
    obs = dp.download("winter wheat", station_id=15557)
    s = dp.series(obs)
    assert list(s.columns) == dp.SERIES_COLUMNS
    assert list(s.columns)[-4:] == ["quality_byte", "quality_byte_meaning", "quality_level",
                                    "quality_level_meaning"]
    pts = s[s.kind == "point"]
    assert 8 in set(pts["quality_byte"].dropna())                      # not dropped by default
    bad = pts[pts.quality_byte == 8].iloc[0]
    assert bad["quality_byte_meaning"] == "incorrect" and bad["phase_id"] == 15
    assert bad["quality_level_meaning"] == "ROUTKLI checked + corrected"
    cur = s[s.kind == "curve"]
    assert cur[["quality_byte", "quality_byte_meaning", "quality_level",
                "quality_level_meaning"]].isna().all().all()
    clean = dp.series(obs, quality=[1, 2, 3])
    assert set(clean.loc[clean.kind == "point", "quality_byte"]) <= {1, 2, 3}
    lv = dp.series(obs, quality_level="10")
    assert set(lv.loc[lv.kind == "point", "quality_level"]) == {10}


def test_summary_quality_counts(mixed):
    obs = dp.download("winter wheat", station_id=15557)
    sm = dp.summary(obs)
    assert list(sm.columns) == dp.SUMMARY_COLUMNS
    assert list(sm.columns)[-7:] == ["n_not_flagged", "n_corrected", "n_confirmed", "n_doubtful",
                                     "n_incorrect", "n_no_quality_byte", "quality_levels"]
    counts = sm[["n_not_flagged", "n_corrected", "n_confirmed", "n_doubtful", "n_incorrect",
                 "n_no_quality_byte"]].sum(axis=1)
    assert (counts == sm["n"]).all()
    r = sm.set_index("phase_id")
    assert r.loc[15, "n_incorrect"] == 1 and r.loc[15, "n_not_flagged"] == 10
    assert r.loc[18, "n_doubtful"] == 1 and r.loc[19, "n_corrected"] == 1
    assert r.loc[21, "n_confirmed"] == 1 and r.loc[24, "n_no_quality_byte"] == 1
    assert r.loc[15, "quality_levels"] == "1;10"                       # 2026 rows are level 1
    f = dp.summary(obs, quality=[1]).set_index("phase_id")
    assert f.loc[15, "n"] == 10 and f.loc[15, "n_incorrect"] == 0
    assert dp.summary(obs, quality_level=10).set_index("phase_id").loc[15, "quality_levels"] == "10"


def test_plot_marks_flagged_points(mixed):
    mpl = pytest.importorskip("matplotlib")
    mpl.use("Agg")
    obs = dp.download("winter wheat", station_id=15557)
    ax = dp.plot_station(obs, 15557, years=(2024, 2026))
    markers = [ln.get_marker() for ln in ax.lines if len(ln.get_xdata())]
    assert "X" in markers                                              # doubtful / incorrect
    hollow = [ln for ln in ax.lines if ln.get_marker() == "o" and ln.get_markerfacecolor() == "white"]
    assert hollow                                                      # corrected / confirmed
    labels = [t.get_text() for leg in ax.findobj(mpl.legend.Legend) for t in leg.get_texts()]
    assert "doubtful / incorrect (5, 8)" in labels and "winter wheat" in labels
    ax2 = dp.plot_station(obs, 15557, years=(2024, 2026), quality=[1])
    assert "X" not in [ln.get_marker() for ln in ax2.lines if len(ln.get_xdata())]


def test_cli_quality(mixed, tmp_path):
    allobs, clean = tmp_path / "all.csv", tmp_path / "clean.csv"
    assert main(["download", "--crops", "winter wheat", "--station-id", "15557", "--quiet",
                 "--out", str(allobs)]) == 0
    assert main(["download", "--crops", "winter wheat", "--station-id", "15557", "--quiet",
                 "--quality", "1,2,3", "--quality-level", "10", "--out", str(clean)]) == 0
    a, c = pd.read_csv(allobs), pd.read_csv(clean)
    assert 8 in set(a["quality_byte"]) and set(c["quality_byte"]) <= {1, 2, 3}
    assert set(c["quality_level"]) == {10} and len(c) < len(a)
    summ = tmp_path / "s.csv"
    assert main(["summary", "--in", str(allobs), "--quality", "8", "--out", str(summ)]) == 0
    s = pd.read_csv(summ)
    assert s["n"].tolist() == [1] and s["n_incorrect"].tolist() == [1]
    ser = tmp_path / "ser.csv"
    assert main(["series", "--in", str(allobs), "--quality-level", "1", "--out", str(ser)]) == 0
    sr = pd.read_csv(ser)
    assert set(sr.loc[sr.kind == "point", "quality_level"]) == {1}
    assert main(["download", "--crops", "winter wheat", "--quality", "4"]) == 1   # usage error


def test_quality_columns_regex_sanity():
    # the download fixture rows really carry quality bytes in column 7
    line = (FIX / RECENT.rsplit("/", 1)[1]).read_text(encoding="cp1252").splitlines()[1]
    assert re.match(r"\s*15557;\s*2024;\s*10;\s*202;\s*10;\s*20241007;\s*1;", line)
