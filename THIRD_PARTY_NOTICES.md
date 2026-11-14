# Third-party notices, data licences and citations

This file lists every dataset, scientific method, library and service that `dwdpheno` (the Python
package in this repository) and **DWDPheno Studio** (the desktop app and the web app at
<https://bluerror.com/dwdpheno/>) use, with its licence, the attribution its licence asks for, and
where the licence was checked. The source code of `dwdpheno` is MIT-licensed (see [`LICENSE`](LICENSE));
the third-party material below keeps its own licence.

Licences were checked against the primary sources linked in each table on 14 November 2026.

DWDPheno is an independent project. It is not affiliated with, or endorsed by, the Deutscher
Wetterdienst (DWD), the Bundesamt für Kartographie und Geodäsie (BKG), GeoNames, the
OpenStreetMap Foundation, the Julius Kühn-Institut or any other provider named here.

---

## 1. Data

| Data | Used by | Licence | Licence verified at |
|---|---|---|---|
| Phenological observations, station metadata and phase definitions (incl. BBCH codes), DWD Climate Data Center, <https://opendata.dwd.de/climate_environment/CDC/observations_germany/phenology/> | downloaded at run time by the package and Studio; small excerpts in `tests/fixtures/` (source distribution only) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | [DWD CDC terms of use](https://opendata.dwd.de/climate_environment/CDC/Terms_of_use.pdf) (status May 2024), [dwd.de/copyright](https://www.dwd.de/copyright), [DWD source-note templates](https://www.dwd.de/DE/service/rechtliche_hinweise/vorlagen_quellenangabe.html) |
| Administrative boundaries VG2500 (Verwaltungsgebiete 1 : 2 500 000), BKG, version of 1 January 2026, downloaded 2026 | bundled: `dwdpheno/data/states.geojson`, `counties.geojson`, `regions.txt`; Studio map outlines | [Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0)](https://www.govdata.de/dl-de/by-2-0) | [BKG terms of use and source note for VG2500](https://sgx.geodatenzentrum.de/web_public/gdz/lizenz/deu/nutzungsbedingungen_vg2500.pdf) (document of 30.06.2025), [licence text](https://www.govdata.de/dl-de/by-2-0) |
| Populated places, GeoNames `DE` dump, <https://download.geonames.org/export/dump/DE.zip> | bundled: `dwdpheno/data/cities.txt`; Studio place search | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | [geonames.org/about](https://www.geonames.org/about.html), [dump readme](https://download.geonames.org/export/dump/readme.txt) |
| Base-map tiles, `tile.openstreetmap.org` (Studio only, optional, can be switched off) | loaded by the browser / WebView while the map is shown; not stored or redistributed | map data: [ODbL 1.0](https://opendatacommons.org/licenses/odbl/); use of the tile server: [OSMF Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/) | [openstreetmap.org/copyright](https://www.openstreetmap.org/copyright), [OSMF attribution guidelines](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines) |
| BBCH scale: names of the principal growth stages (0–9) used for plot axes and stage bands | `dwdpheno._series.BBCH_PRINCIPAL_STAGES`, Studio BBCH plots | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | [DataCite record of doi:10.5073/20180906-074619](https://api.datacite.org/dois/10.5073/20180906-074619) |

### Required source notes

**DWD.** CC BY 4.0 requires naming the source, the licence and a link, and saying whether the data
were changed. DWD's own templates are `Quelle: Deutscher Wetterdienst` for unchanged data and
`Datenbasis: Deutscher Wetterdienst, <what was changed>` for changed data (examples given by DWD:
"Einzelwerte gemittelt", "eigene Elemente ergänzt"). `dwdpheno` and Studio change the data
(English crop and phase names, decoded quality flags, county and nearest place added, curves and
statistics computed), so they use:

> Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt. Licence: CC BY 4.0
> (https://creativecommons.org/licenses/by/4.0/).

**BKG (VG2500).** The BKG terms of use for VG2500 require a clearly visible source note and a change
note on every public display or distribution of the data or of a work made from it; on web pages
"BKG" must link to <https://www.bkg.bund.de> and "dl-de/by-2-0" to <https://www.govdata.de/dl-de/by-2-0>.
The bundled boundaries were reprojected from UTM 32N to WGS84 longitude/latitude, rounded to five
decimals, limited to land areas and given English region types, so the note is:

> © BKG (2026) dl-de/by-2-0 (Daten verändert), Datenquellen:
> https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/datenquellen_vg_nuts.pdf

**GeoNames.** CC BY 4.0. The bundled list keeps places with a population of at least 1000 and adds
the federal state:

> Place names and coordinates: GeoNames (https://www.geonames.org/), CC BY 4.0, filtered.

**OpenStreetMap.** Shown in the corner of the Studio map whenever the base map is on:
"© OpenStreetMap contributors", linked to <https://www.openstreetmap.org/copyright>.

**BBCH.** Meier, U. (ed.) (2018): *Growth stages of mono- and dicotyledonous plants: BBCH Monograph.*
Open Agrar Repositorium, Quedlinburg. <https://doi.org/10.5073/20180906-074619>. CC BY 4.0.
The BBCH codes of the individual phases come from the DWD phase definitions.

### Crediting the data in your own work

If you publish results obtained with `dwdpheno` or Studio, credit the data, for example:

> Phenological data: Datenbasis: Deutscher Wetterdienst, <your changes, e.g. "Einzelwerte
> gemittelt">, CC BY 4.0. County boundaries: © BKG (2026) dl-de/by-2-0 (Daten verändert).
> Places: GeoNames, CC BY 4.0.

---

## 2. Scientific methods

Only standard, published methods are implemented. None of them is subject to a licence; they are
cited for scientific credit.

| Method | Where | Reference |
|---|---|---|
| Monotone piecewise-cubic Hermite interpolation (PCHIP) of BBCH stage over time | `dwdpheno._series.pchip`, Studio engine (`series`) | Fritsch, F. N. & Carlson, R. E. (1980): Monotone piecewise cubic interpolation. *SIAM J. Numer. Anal.* 17(2), 238–246. <https://doi.org/10.1137/0717021> |
| PCHIP node slopes: weighted harmonic mean of the neighbouring secants | same | Fritsch, F. N. & Butland, J. (1984): A method for constructing local monotone piecewise cubic interpolants. *SIAM J. Sci. Stat. Comput.* 5(2), 300–304. <https://doi.org/10.1137/0905021> |
| PCHIP end slopes: shape-preserving three-point formula | same | Moler, C. B. (2004): *Numerical Computing with MATLAB*, ch. 3. SIAM. <https://doi.org/10.1137/1.9780898717952> |
| Great-circle distance (haversine formula), radius / nearest-station search and nearest place | `dwdpheno._stations.haversine_km`, Studio engine and UI | Sinnott, R. W. (1984): Virtues of the haversine. *Sky and Telescope* 68(2), 159. (No DOI; citation checked against secondary sources only.) |
| Inverse transverse Mercator projection (UTM 32N → WGS84) when building the boundary files | `tools/build_data.py` (developer tool) | Snyder, J. P. (1987): *Map Projections — A Working Manual.* USGS Professional Paper 1395. <https://doi.org/10.3133/pp1395> |
| Trend of day of year over years: ordinary least-squares slope × 10 (days per decade) | `summary()`, `plot_phase_trend()`, Studio summary and phase-timing plot | standard least squares; no specific source |
| Point in polygon (county lookup, lasso/polygon selection) | package and Studio engine | standard even–odd (ray-crossing) rule; no specific source |

Mann–Kendall tests and Sen's (Theil–Sen) slope are **not** implemented.

---

## 3. Python package: software dependencies

`dwdpheno` does not bundle or copy code from other projects. It imports the following packages,
which are installed separately by pip under their own licences:

| Package | Needed for | Licence (SPDX) | Verified at |
|---|---|---|---|
| pandas | always | BSD-3-Clause | [PyPI](https://pypi.org/project/pandas/) |
| NumPy | always | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | [PyPI](https://pypi.org/project/numpy/) |
| Matplotlib | optional extra `plot` | Matplotlib License (PSF-based) | [PyPI](https://pypi.org/project/matplotlib/) |
| pytest | optional extra `test` | MIT | [PyPI](https://pypi.org/project/pytest/) |
| setuptools | building only | MIT | [PyPI](https://pypi.org/project/setuptools/) |

The wheel and source distribution contain the reference data listed in section 1 (BKG,
GeoNames); the source distribution also contains short DWD excerpts in `tests/fixtures/`. Their
licences are recorded in the package metadata (`License-Expression: MIT AND CC-BY-4.0 AND
DL-DE-BY-2.0`) and this file is shipped as a licence file.

---

## 4. DWDPheno Studio: bundled components

DWDPheno Studio is distributed as installers and run as a web app. Its own licence is shown during
installation. It contains the following third-party components; their full licence texts are
shipped with the app (`web/third-party-notices.txt`, also shown in the app under
**Licences & credits**).

| Component | Version | Where | Licence | Verified at |
|---|---|---|---|---|
| Leaflet | 1.9.4 | web UI (`web/vendor/leaflet`, incl. its marker and layer images) | BSD-2-Clause | [LICENSE at v1.9.4](https://github.com/Leaflet/Leaflet/blob/v1.9.4/LICENSE) (identical to the bundled file) |
| plotly.js | 3.6.0 | web UI (`web/vendor/plotly.min.js`) | MIT | [LICENSE at v3.6.0](https://github.com/plotly/plotly.js/blob/v3.6.0/LICENSE) |
| .NET 8 runtime (self-contained) | 8.0 | all builds | MIT, plus the runtime's third-party notices | [LICENSE](https://github.com/dotnet/runtime/blob/main/LICENSE.TXT), [THIRD-PARTY-NOTICES](https://github.com/dotnet/runtime/blob/main/THIRD-PARTY-NOTICES.TXT) |
| ASP.NET Core 8 | 8.0 | web/Linux build | MIT | [LICENSE](https://github.com/dotnet/aspnetcore/blob/main/LICENSE.txt) |
| WPF / Windows Desktop runtime | 8.0 | Windows desktop build | MIT | [LICENSE](https://github.com/dotnet/wpf/blob/main/LICENSE.TXT) |
| Microsoft.Web.WebView2 SDK (incl. `WebView2Loader`) | 1.0.2210.55 | Windows desktop build | BSD-3-Clause-style Microsoft licence, plus the package's NOTICE | [nuget.org licence](https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.2210.55/License) |
| Microsoft Edge WebView2 Runtime bootstrapper (`MicrosoftEdgeWebview2Setup.exe`) | — | Windows installer, run only when the runtime is missing | Microsoft software; packaging it with an app is described as allowed in [Microsoft's distribution guide](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution). The bootstrapper's own licence terms: **unverified** | — |
| GNU Fortran runtime (`libgfortran`) and `libgcc` | GCC 16.1.0 (Windows, winlibs MinGW-w64 UCRT, linked statically); GCC 15.2 (Linux, the system's `libgfortran5` is used, not shipped) | Fortran engine | GPL-3.0-or-later WITH GCC-exception-3.1 | [GCC Runtime Library Exception 3.1](https://www.gnu.org/licenses/gcc-exception-3.1.html), [libgfortran source header](https://github.com/gcc-mirror/gcc/blob/master/libgfortran/runtime/main.c) |
| GNU quad-precision math library (`libquadmath`) | GCC 16.1.0 | Windows engine (`dwdpheno.dll`, `dwdpheno-engine.exe`), linked statically | LGPL-2.1-or-later | [COPYING.LIB](https://github.com/gcc-mirror/gcc/blob/master/libquadmath/COPYING.LIB) |
| MinGW-w64 runtime | winlibs GCC 16.1.0 build | Windows engine, linked statically | ZPL-2.1 / public domain / BSD-style parts that require their notices | [COPYING.MinGW-w64-runtime](https://github.com/mingw-w64/mingw-w64/blob/master/COPYING.MinGW-w64-runtime/COPYING.MinGW-w64-runtime.txt) |
| Inno Setup | — | Windows installer | Inno Setup License | [jrsoftware.org/files/is/license.txt](https://jrsoftware.org/files/is/license.txt) |

Not bundled: no web fonts (the UI uses the system font stack) and no third-party icon sets. The app
icon is an original drawing (`tools/make_icon.ps1`) and the toolbar icons are hand-written inline SVG.
On Linux the engine uses the system's `libgfortran5` and `curl`, which are installed by the package
manager, not shipped.

### OpenStreetMap tile use

The Studio base map loads tiles directly from `tile.openstreetmap.org` in the user's browser (or in
WebView2 in the Windows app), shows the OSM attribution in the map corner, sends the normal
browser Referer (Referrer-Policy `strict-origin-when-cross-origin`), does not prefetch or store
tiles, and can be switched off ("base map"). The OSM tile servers are a donated service with no
guarantee; heavy use can be blocked under the [Tile Usage Policy](https://operations.osmfoundation.org/policies/tiles/).
