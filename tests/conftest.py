"""Offline test harness: the HTTP layer is replaced by a fake that serves the real (trimmed)
DWD files in ``tests/fixtures`` by URL; anything else is a 404."""
from pathlib import Path

import pytest

from dwdpheno import _catalog as catalog, _http, _stations as stations

FIX = Path(__file__).parent / "fixtures"
B = catalog.BASE_URL
H = catalog.HELP_URL

ROUTES = {
    f"{H}/PH_Beschreibung_Phaenologie_Stationen_Jahresmelder.txt":
        "PH_Beschreibung_Phaenologie_Stationen_Jahresmelder.txt",
    f"{H}/PH_Beschreibung_Phaenologie_Stationen_Sofortmelder.txt":
        "PH_Beschreibung_Phaenologie_Stationen_Sofortmelder.txt",
    f"{H}/PH_Beschreibung_Pflanze.txt": "PH_Beschreibung_Pflanze.txt",
    f"{H}/PH_Beschreibung_Phase.txt": "PH_Beschreibung_Phase.txt",
    f"{B}/annual_reporters/crops/historical/": "listing_annual_crops_historical.html",
    f"{B}/annual_reporters/crops/recent/": "listing_annual_crops_recent.html",
    f"{B}/annual_reporters/fruit/historical/": "listing_annual_fruit_historical.html",
    f"{B}/annual_reporters/crops/recent/"
    "PH_Beschreibung_Phasendefinition_Jahresmelder_Landwirtschaft_Kulturpflanze.txt":
        "PH_Beschreibung_Phasendefinition_Jahresmelder_Landwirtschaft_Kulturpflanze.txt",
    f"{B}/annual_reporters/crops/historical/"
    "PH_Jahresmelder_Landwirtschaft_Kulturpflanze_Winterweizen_1925_2024_hist.txt":
        "PH_Jahresmelder_Landwirtschaft_Kulturpflanze_Winterweizen_1925_2024_hist.txt",
    f"{B}/annual_reporters/crops/recent/"
    "PH_Jahresmelder_Landwirtschaft_Kulturpflanze_Winterweizen_akt.txt":
        "PH_Jahresmelder_Landwirtschaft_Kulturpflanze_Winterweizen_akt.txt",
}


class FakeDWD:
    def __init__(self):
        self.calls = []
        self.extra = {}

    def __call__(self, url, timeout=None, retries=None):
        self.calls.append(url)
        if url in self.extra:
            return self.extra[url]
        if url in ROUTES:
            return (FIX / ROUTES[url]).read_bytes()
        raise _http.NetworkError(f"GET {url} failed: HTTP Error 404", 404)


@pytest.fixture
def fake(monkeypatch, tmp_path, request):
    """Fake DWD server + a fresh, empty cache directory."""
    if request.node.get_closest_marker("network"):
        pytest.skip("not for network tests")
    f = FakeDWD()
    monkeypatch.setattr(_http, "_get", f)
    monkeypatch.setenv("DWDPHENO_CACHE", str(tmp_path / "cache"))
    stations._build_table.cache_clear()
    catalog._PHASE_CACHE.clear()
    return f
