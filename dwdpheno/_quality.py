"""DWD quality flags: meanings and filtering."""
from __future__ import annotations

from typing import Iterable, List, Optional, Union

import pandas as pd

from ._text import as_list

QUALITY_BYTE = {1: "not flagged", 2: "corrected", 3: "confirmed despite flag", 5: "doubtful",
                8: "incorrect", 0: "(no quality byte)"}
QUALITY_LEVEL = {1: "pre-load check only", 2: "pre-load check (immediate reporters)",
                 7: "ROUTKLI checked", 10: "ROUTKLI checked + corrected"}

QualityArg = Union[None, int, str, Iterable[int]]


def parse_codes(value: QualityArg, known: dict, what: str) -> Optional[List[int]]:
    """``None`` → ``None``; ``8``, ``"1,2,3"`` or ``[1, 2, 3]`` → sorted list of known codes."""
    vals = as_list(value)
    if vals is None:
        return None
    try:
        codes = sorted({int(v) for v in vals})
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be integer codes, got {value!r}") from None
    bad = [c for c in codes if c not in known]
    if bad or not codes:
        raise ValueError(f"unknown {what} code(s) {bad or value!r}; valid: "
                         f"{', '.join(str(k) for k in sorted(known))}")
    return codes


def quality_bytes(df: pd.DataFrame) -> pd.Series:
    """Quality byte per row as int; a missing byte (or column) counts as 0."""
    if "quality_byte" not in df.columns:
        return pd.Series(0, index=df.index, dtype="int64")
    return pd.to_numeric(df["quality_byte"], errors="coerce").fillna(0).astype("int64")


def filter_quality(df: pd.DataFrame, quality: QualityArg = None,
                   quality_level: QualityArg = None) -> pd.DataFrame:
    """Keep the rows whose quality byte / quality level is in the given codes (default: all)."""
    qb = parse_codes(quality, QUALITY_BYTE, "quality byte")
    ql = parse_codes(quality_level, QUALITY_LEVEL, "quality level")
    keep = pd.Series(True, index=df.index)
    if qb is not None:
        keep &= quality_bytes(df).isin(qb)
    if ql is not None:
        lv = (pd.to_numeric(df["quality_level"], errors="coerce") if "quality_level" in df.columns
              else pd.Series(float("nan"), index=df.index))
        keep &= lv.isin(ql)
    return df[keep.astype(bool)]


def meanings(codes: pd.Series, table: dict) -> pd.Series:
    """Codes → meaning strings (missing code → missing)."""
    return pd.to_numeric(codes, errors="coerce").map(table).astype("string")
