"""The DWD phenology catalog: directory listings, data files, plant / phase names, BBCH codes."""
from __future__ import annotations

import datetime
import html
import re
from typing import Dict, List, NamedTuple, Optional, Sequence, Union

import pandas as pd

from . import _http
from ._text import as_list, select_names, squash

BASE_URL = "https://opendata.dwd.de/climate_environment/CDC/observations_germany/phenology"
HELP_URL = "https://opendata.dwd.de/climate_environment/CDC/help"
PLANT_URL = f"{HELP_URL}/PH_Beschreibung_Pflanze.txt"
PHASE_URL = f"{HELP_URL}/PH_Beschreibung_Phase.txt"

REPORTERS = {"annual": ("annual_reporters", "Jahresmelder"),
             "immediate": ("immediate_reporters", "Sofortmelder")}
GROUPS = {"annual": ("crops", "wild", "fruit", "vine", "farming"),
          "immediate": ("crops", "wild", "fruit", "vine")}
PARTITIONS = ("historical", "recent")
GROUP_TOKENS = ("Landwirtschaft_Kulturpflanze", "Wildwachsende_Pflanze", "Obst",
                "Weinrebe", "Wein", "Feldarbeit", "Weidegang")

CROP_COLUMNS = ["crop", "crop_de", "species", "objekt_id", "dwd_token", "group", "reporters",
                "first_year", "last_year", "files"]
PHASE_COLUMNS = ["objekt_id", "crop", "phase_id", "phase_name", "bbch_code"]

# fixed exceptions of the token -> plant rule
TOKEN_OBJEKT = {"Rueben_ohne_Sortenangabe": 250}
ENGLISH_OVERRIDE = {250: "beet (variety unknown)"}   # DWD calls both 25 and 250 "beet"

_HREF = re.compile(r'<a\s+href="([^"?#]+)"', re.IGNORECASE)
_GROUP_ALT = "|".join(sorted(GROUP_TOKENS, key=len, reverse=True))
_DATA_RE = {
    rep: re.compile(rf"^PH_{infix}_({_GROUP_ALT})_(.+?)"
                    rf"(?:_(\d{{4}})_(\d{{4}})_hist|_(hist)|_(akt))\.txt$")
    for rep, (_, infix) in REPORTERS.items()
}
_RECORD_END = re.compile(r";\s*eor\s*;", re.IGNORECASE)


class DataFile(NamedTuple):
    reporter: str
    group: str
    partition: str
    group_token: str
    crop: str          # the DWD crop token, e.g. "Apfel_fruehe_Reife"
    y0: Optional[int]
    y1: Optional[int]
    filename: str
    url: str


def _net(cache=None, offline=False, max_age_days=1.0) -> dict:
    return dict(cache=cache, offline=offline, max_age_days=max_age_days)


# ---------------------------------------------------------------------------------------------
#  DWD text tables
# ---------------------------------------------------------------------------------------------

def read_table(raw: bytes) -> pd.DataFrame:
    """Parse a small DWD text table as strings.

    DWD files are ``;``-separated, blank-padded, windows-1252, and every record ends in
    ``eor;`` (sometimes ``eor ;``).  Records may contain line breaks, so they are split on the
    record end, not on newlines.  Empty cells become missing.
    """
    text = raw.decode("cp1252", errors="replace")
    parts = _RECORD_END.split(text)
    if len(parts) < 2:                       # no record ends at all: one record per line
        parts = text.splitlines()
    header = [h.strip() for h in parts[0].split(";")]
    while header and header[-1] in ("", "eor"):
        header.pop()
    n = len(header)
    rows = []
    for rec in parts[1:]:
        rec = " ".join(rec.replace("\x1a", " ").split())
        if not rec:
            continue
        cells = [c.strip() for c in rec.split(";")]
        rows.append([c or None for c in (cells + [""] * n)[:n]])
    return pd.DataFrame(rows, columns=header, dtype=object)


def _is_missing_text(s: pd.Series) -> pd.Series:
    return s.isna() | s.astype("string").str.fullmatch(r"-*").fillna(True).astype(bool)


def parse_plants(raw: bytes) -> pd.DataFrame:
    """``PH_Beschreibung_Pflanze.txt`` → ``objekt_id, crop_de, crop, species``."""
    df = read_table(raw)
    df.columns = [c.lower() for c in df.columns]
    out = pd.DataFrame({
        "objekt_id": pd.to_numeric(df["objekt_id"], errors="coerce").astype("Int64"),
        "crop_de": df["objekt"].astype("string"),
        "crop": df["objekt_englisch"].astype("string"),
        "species": df["objekt_latein"].astype("string"),
    }).dropna(subset=["objekt_id"])
    for c in ("crop", "species"):
        out[c] = out[c].where(~_is_missing_text(out[c]), None)
    for oid, name in ENGLISH_OVERRIDE.items():
        out.loc[out["objekt_id"] == oid, "crop"] = name
    out["crop"] = out["crop"].fillna(out["crop_de"])
    return out.drop_duplicates("objekt_id").reset_index(drop=True)


def parse_phase_names(raw: bytes) -> pd.DataFrame:
    """``PH_Beschreibung_Phase.txt`` → ``phase_id, phase_name`` (English), ``phase_name_de``."""
    df = read_table(raw)
    df.columns = [c.lower() for c in df.columns]
    out = pd.DataFrame({
        "phase_id": pd.to_numeric(df["phase_id"], errors="coerce").astype("Int64"),
        "phase_name": df["phase_englisch"].astype("string"),
        "phase_name_de": df["phase"].astype("string"),
    }).dropna(subset=["phase_id"])
    out["phase_name"] = out["phase_name"].fillna(out["phase_name_de"])
    return out.drop_duplicates("phase_id").reset_index(drop=True)


_PHASEDEF_RENAME = {"Objekt_id": "objekt_id", "Objekt": "objekt_de", "Phasen_id": "phase_id",
                    "Phase_id": "phase_id", "Phase": "phase_de", "BBCH_Code": "bbch_code"}


def parse_phase_definitions(raw: bytes) -> pd.DataFrame:
    """Phase-definition file → ``objekt_id, objekt_de, phase_id, phase_de, bbch_code``."""
    cols = ["objekt_id", "objekt_de", "phase_id", "phase_de", "bbch_code"]
    df = read_table(raw).rename(columns=_PHASEDEF_RENAME)
    if "objekt_id" not in df.columns or "phase_id" not in df.columns:
        return pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df = df[cols].copy()
    for c in ("objekt_id", "phase_id"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    bbch = df["bbch_code"].astype("string").str.strip()
    bbch = bbch.str.replace(r"^(-?\d+)\.0$", r"\1", regex=True)
    df["bbch_code"] = bbch.where(bbch.str.match(r"^\d").fillna(False).astype(bool), None)
    for c in ("objekt_de", "phase_de"):
        df[c] = df[c].astype("string")
    return df.dropna(subset=["objekt_id", "phase_id"])


def plants(**net) -> pd.DataFrame:
    """DWD plant names: ``objekt_id, crop_de, crop`` (English), ``species`` (Latin)."""
    return parse_plants(_http.fetch(PLANT_URL, **_net(**net)))


def phase_names(**net) -> pd.DataFrame:
    """DWD phase names: ``phase_id, phase_name`` (English), ``phase_name_de``."""
    return parse_phase_names(_http.fetch(PHASE_URL, **_net(**net)))


# ---------------------------------------------------------------------------------------------
#  Listings and data files
# ---------------------------------------------------------------------------------------------

def folder_url(reporter: str, group: str, partition: str) -> str:
    return f"{BASE_URL}/{REPORTERS[reporter][0]}/{group}/{partition}/"


def parse_listing(page: Union[bytes, str]) -> List[str]:
    """File names linked from an Apache/nginx directory index (no sub-folders)."""
    if isinstance(page, bytes):
        page = page.decode("utf-8", errors="replace")
    out = []
    for href in _HREF.findall(page):
        name = html.unescape(href)
        if name.endswith("/") or name.startswith(("..", "/")):
            continue
        out.append(name)
    return out


def list_folder(reporter: str, group: str, partition: str, **net) -> List[str]:
    """File names in one DWD folder; a missing folder gives ``[]``."""
    try:
        return parse_listing(_http.fetch(folder_url(reporter, group, partition), **_net(**net)))
    except _http.NetworkError as e:
        if e.status in (404, 410):
            return []
        raise


def parse_data_filename(name: str, reporter: str):
    """``(group_token, crop_token, y0, y1)`` of a data file name, else ``None``.

    ``..._hist.txt`` without a year range is a historical file with unknown years.
    """
    m = _DATA_RE[reporter].match(name)
    if not m:
        return None
    gtok, crop, y0, y1, _hist, _akt = m.groups()
    if crop.endswith(("_Spezifizierung", "_Notiz")):
        return None
    return gtok, crop, (int(y0) if y0 else None), (int(y1) if y1 else None)


def data_files(reporters: Sequence[str] = ("annual", "immediate"),
               partitions: Sequence[str] = PARTITIONS,
               groups: Optional[Sequence[str]] = None, **net) -> List[DataFile]:
    """All data files; of duplicate historical versions only the greatest ``y1`` is kept."""
    best: Dict[tuple, DataFile] = {}
    for rep in reporters:
        for grp in GROUPS[rep]:
            if groups is not None and grp not in groups:
                continue
            for part in partitions:
                for name in list_folder(rep, grp, part, **net):
                    p = parse_data_filename(name, rep)
                    if p is None:
                        continue
                    gtok, crop, y0, y1 = p
                    f = DataFile(rep, grp, part, gtok, crop, y0, y1, name,
                                 folder_url(rep, grp, part) + name)
                    key = (rep, grp, part, gtok, crop)
                    old = best.get(key)
                    if old is None or (y1 or 0, -(y0 or 0)) > (old.y1 or 0, -(old.y0 or 0)):
                        best[key] = f
    return sorted(best.values(), key=lambda d: (d.crop, d.reporter, d.partition, d.group))


def plant_of_token(token: str, plant_table: pd.DataFrame) -> Optional[int]:
    """Objekt id of a file token: equal squashed German name, else the shortest German name
    whose squashed form starts with the squashed token, else ``None``."""
    if token in TOKEN_OBJEKT:
        return TOKEN_OBJEKT[token]
    st = squash(token)
    names = [(int(o), str(n), squash(n)) for o, n in
             zip(plant_table["objekt_id"], plant_table["crop_de"]) if pd.notna(n)]
    exact = [o for o, _, s in names if s == st]
    if exact:
        return exact[0]
    pref = sorted((len(n), o) for o, n, s in names if s.startswith(st))
    return pref[0][1] if pref else None


# ---------------------------------------------------------------------------------------------
#  Crop catalog and selection
# ---------------------------------------------------------------------------------------------

def _catalog(files: Sequence[DataFile], plant_table: pd.DataFrame) -> pd.DataFrame:
    by_id = plant_table.set_index("objekt_id")
    rows: Dict[str, dict] = {}
    for f in files:
        r = rows.get(f.crop)
        if r is None:
            oid = plant_of_token(f.crop, plant_table)
            if oid is not None and oid in by_id.index:
                p = by_id.loc[oid]
                names = (p["crop"], p["crop_de"], p["species"])
            else:
                oid, names = None, (f.crop.replace("_", " "), f.crop.replace("_", " "), None)
            r = rows[f.crop] = {"crop": names[0], "crop_de": names[1], "species": names[2],
                                "objekt_id": oid, "dwd_token": f.crop, "group": f.group,
                                "reporters": set(), "first_year": None, "last_year": None,
                                "files": 0}
        r["reporters"].add(f.reporter)
        r["files"] += 1
        if f.y0 is not None:
            r["first_year"] = f.y0 if r["first_year"] is None else min(r["first_year"], f.y0)
        if f.y1 is not None:
            r["last_year"] = f.y1 if r["last_year"] is None else max(r["last_year"], f.y1)
        if f.partition == "recent":     # recent files run up to the current year
            r["last_year"] = max(r["last_year"] or 0, datetime.date.today().year)
    for r in rows.values():
        r["reporters"] = ";".join(x for x in ("annual", "immediate") if x in r["reporters"])
    df = pd.DataFrame(list(rows.values()), columns=CROP_COLUMNS)
    for c in ("objekt_id", "first_year", "last_year", "files"):
        df[c] = pd.to_numeric(df[c]).astype("Int64")
    for c in ("crop", "crop_de", "species", "dwd_token", "group", "reporters"):
        df[c] = df[c].astype("string")
    df = df.assign(_k=df["crop"].str.lower()).sort_values(["group", "_k", "dwd_token"],
                                                          kind="stable")
    return df.drop(columns="_k").reset_index(drop=True)


def crops(*, cache=None, offline: bool = False, max_age_days: float = 1.0) -> pd.DataFrame:
    """The crop / species catalog: one row per DWD crop token.

    Columns ``crop`` (English), ``crop_de`` (German), ``species`` (Latin), ``objekt_id``,
    ``dwd_token``, ``group``, ``reporters`` (``annual``, ``immediate`` or ``annual;immediate``),
    ``first_year``/``last_year`` (from the historical file names; ``last_year`` is the current
    year when a recent file exists) and ``files``.
    Sorted by group and English name.
    """
    net = _net(cache, offline, max_age_days)
    return _catalog(data_files(**net), plants(**net))


def select_crops(queries: Sequence[str], catalog: pd.DataFrame) -> pd.DataFrame:
    """Catalog rows selected by crop queries (English, German or token; exact match first,
    otherwise every query word must be a prefix of a word of one of the names)."""
    cands = list(zip(catalog["crop"], catalog["crop_de"], catalog["dwd_token"]))
    hit = sorted({i for q in queries for i in select_names(q, cands)})
    return catalog.iloc[hit]


# ---------------------------------------------------------------------------------------------
#  Phases and BBCH codes
# ---------------------------------------------------------------------------------------------

def phase_files(reporters: Sequence[str] = ("annual", "immediate"),
                groups: Optional[Sequence[str]] = None, **net) -> List[str]:
    """URLs of the phase-definition files (recent folder preferred over historical)."""
    urls: Dict[tuple, str] = {}
    for rep in reporters:
        for grp in GROUPS[rep]:
            if groups is not None and grp not in groups:
                continue
            for part in ("recent", "historical"):
                for name in list_folder(rep, grp, part, **net):
                    if name.startswith("PH_Beschreibung_Phasendefinition_") and name.endswith(".txt"):
                        urls.setdefault((rep, grp, name), folder_url(rep, grp, part) + name)
    return list(urls.values())


def load_phase_definitions(reporters: Sequence[str] = ("annual", "immediate"),
                           groups: Optional[Sequence[str]] = None, **net) -> pd.DataFrame:
    """All phase definitions, one row per ``(objekt_id, phase_id)`` (rows with BBCH preferred)."""
    frames = []
    for url in phase_files(reporters, groups, **net):
        try:
            frames.append(parse_phase_definitions(_http.fetch(url, **_net(**net))))
        except _http.NetworkError as e:
            if e.status not in (404, 410):
                raise
    frames = [f for f in frames if len(f)]
    if not frames:
        return parse_phase_definitions(b"")
    df = pd.concat(frames, ignore_index=True)
    df = df.assign(_nobbch=df["bbch_code"].isna())
    df = df.sort_values(["objekt_id", "phase_id", "_nobbch"], kind="stable")
    df = df.drop_duplicates(["objekt_id", "phase_id"], keep="first")
    return df.drop(columns="_nobbch").reset_index(drop=True)


def name_phases(defs: pd.DataFrame, plant_table: pd.DataFrame,
                phase_table: pd.DataFrame) -> pd.DataFrame:
    """Attach English plant and phase names to phase definitions (German as fallback)."""
    df = defs.merge(plant_table[["objekt_id", "crop"]], on="objekt_id", how="left")
    df = df.merge(phase_table[["phase_id", "phase_name"]], on="phase_id", how="left")
    df["crop"] = df["crop"].astype("string").fillna(df["objekt_de"])
    df["phase_name"] = df["phase_name"].astype("string").fillna(df["phase_de"])
    return df


def phases(crops: Union[None, str, Sequence[str]] = None, *, cache=None, offline: bool = False,
           max_age_days: float = 1.0) -> pd.DataFrame:
    """Phases with BBCH codes, optionally only for the given crops.

    Columns ``objekt_id, crop, phase_id, phase_name, bbch_code`` (English names; ``bbch_code``
    is missing when DWD defines none).
    """
    net = _net(cache, offline, max_age_days)
    plant_table = plants(**net)
    df = name_phases(load_phase_definitions(**net), plant_table, phase_names(**net))
    qs = as_list(crops)
    if qs:
        cat = select_crops(qs, _catalog(data_files(**net), plant_table))
        df = df[df["objekt_id"].isin(cat["objekt_id"].dropna().tolist())]
    df = df.sort_values(["objekt_id", "phase_id"], kind="stable")
    return df[PHASE_COLUMNS].reset_index(drop=True)


_PHASE_CACHE: Dict[tuple, pd.DataFrame] = {}


def find_bbch(phase_id: int, objekt_id: Optional[int] = None, *,
              phase_table: Optional[pd.DataFrame] = None, **net) -> pd.DataFrame:
    """Phase rows (with BBCH code) for a DWD ``phase_id``, optionally for one ``objekt_id``.

    The same ``phase_id`` means different things for different plants; pass ``objekt_id``
    (e.g. 202 = winter wheat, 310 = apple) to disambiguate.
    """
    if phase_table is None:
        key = tuple(sorted((k, str(v)) for k, v in net.items()))
        if key not in _PHASE_CACHE:
            _PHASE_CACHE[key] = phases(**net)
        phase_table = _PHASE_CACHE[key]
    df = phase_table[phase_table["phase_id"] == phase_id]
    if objekt_id is not None:
        df = df[df["objekt_id"] == objekt_id]
    return df.reset_index(drop=True)


def bbch_for(phase_id: int, objekt_id: int, *, phase_table: Optional[pd.DataFrame] = None,
             **net) -> Optional[str]:
    """The BBCH code (string) of one plant's phase, or ``None``."""
    rows = find_bbch(phase_id, objekt_id, phase_table=phase_table, **net)
    if not len(rows) or pd.isna(rows.iloc[0]["bbch_code"]):
        return None
    return str(rows.iloc[0]["bbch_code"])
