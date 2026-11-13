"""Live test against opendata.dwd.de -- deselected by default, run with ``pytest -m network``."""
import pytest

import dwdpheno as dp


@pytest.mark.network
def test_live_recent_download(tmp_path):
    obs = dp.download("winter wheat", partition="recent", reporter="annual",
                      county="Landkreis Kassel", active=True, cache=tmp_path)
    assert list(obs.columns) == dp.OBS_COLUMNS
    assert len(obs) > 0 and set(obs["crop_de"]) == {"Winterweizen"}
    assert obs["bbch_code"].notna().any()
    st = dp.stations(county="Kassel rural district", cache=tmp_path)
    assert len(st) > 0 and set(st["county_id"]) == {"06633"}
    assert st["station_id"].tolist() == dp.stations(county="Landkreis Kassel", cache=tmp_path)[
        "station_id"].tolist()
    assert set(obs["crop"]) == {"winter wheat"}
    assert len(dp.crops(cache=tmp_path)) > 60
