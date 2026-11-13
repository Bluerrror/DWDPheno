"""Folded text matching."""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Optional, Sequence, Union

import pandas as pd

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                          "Ä": "ae", "Ö": "oe", "Ü": "ue", "ẞ": "ss"})
_PUNCT = str.maketrans({c: " " for c in "-_.,()"})
_BLANKS = re.compile(r"\s+")
_SQUASH_WORDS = {"fruehreifend": "fruehe reife", "spaetreifend": "spaete reife"}


def fold(text) -> str:
    """Lower-case, ``ä→ae ö→oe ü→ue ß→ss``, strip accents, ``-_.,()`` → blank, collapse blanks."""
    if text is None or text is pd.NA or (isinstance(text, float) and text != text):
        return ""
    s = str(text).translate(_UMLAUTS).lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return _BLANKS.sub(" ", s.translate(_PUNCT)).strip()


def squash(text) -> str:
    """Folded text without blanks (``fruehreifend``/``spaetreifend`` spelled out first)."""
    return "".join(_SQUASH_WORDS.get(w, w) for w in fold(text).split()).replace(" ", "")


def matches(query, text) -> bool:
    """True when every blank-separated token of the folded query is a substring of the folded text."""
    t = fold(text)
    return all(tok in t for tok in fold(query).split())


def any_match(queries: Sequence[str], text) -> bool:
    return any(matches(q, text) for q in queries)


def select_names(query: str, candidates: Sequence[Sequence]) -> List[int]:
    """Indices of the candidates a (crop) query selects; each candidate is a list of its names.

    1. the candidates having a name equal to the folded query, if there are any;
    2. otherwise those where every query word is a prefix of some word of their names.
    """
    fq = fold(query)
    if not fq:
        return []
    folded = [[f for f in (fold(n) for n in names) if f] for names in candidates]
    exact = [i for i, names in enumerate(folded) if fq in names]
    if exact:
        return exact
    out = []
    for i, names in enumerate(folded):
        words = [w for n in names for w in n.split()]
        if all(any(w.startswith(q) for w in words) for q in fq.split()):
            out.append(i)
    return out


def as_list(value: Union[None, str, Iterable], sep: str = ",") -> Optional[List]:
    """``None`` → ``None``; ``"a,b"`` → ``["a", "b"]``; any other iterable → list; scalar → ``[scalar]``."""
    if value is None:
        return None
    if isinstance(value, str):
        return [v.strip() for v in value.split(sep) if v.strip()]
    if isinstance(value, Iterable):
        return list(value)
    return [value]
