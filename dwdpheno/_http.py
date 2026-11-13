"""HTTP access to opendata.dwd.de with an on-disk cache (stdlib ``urllib`` only)."""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from pathlib import Path
from typing import Optional, Union

from . import __version__

USER_AGENT = f"dwdpheno/{__version__} (+https://github.com/Bluerrror/DWDPheno)"
TIMEOUT = 120

CacheArg = Union[None, bool, str, os.PathLike]


class DWDPhenoError(Exception):
    """Base class of all dwdpheno errors."""


class NoMatchError(DWDPhenoError, LookupError):
    """A selection (stations, crops, places) matched nothing."""


class NetworkError(DWDPhenoError, OSError):
    """A download failed, or a file is missing from the cache in offline mode."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def default_cache_dir() -> Path:
    """``$DWDPHENO_CACHE``, else the platform user cache directory."""
    env = os.environ.get("DWDPHENO_CACHE")
    if env:
        return Path(env).expanduser()
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "dwdpheno" / "cache"
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "dwdpheno"
    return Path.home() / ".cache" / "dwdpheno"


def cache_dir(cache: CacheArg) -> Optional[Path]:
    """Resolve the ``cache`` argument: ``None``/``True`` = default, ``False`` = off, else a path."""
    if cache is False:
        return None
    if cache is None or cache is True:
        return default_cache_dir()
    return Path(cache).expanduser()


def _get(url: str, timeout: float = TIMEOUT, retries: int = 3) -> bytes:
    """GET ``url``; retries with exponential backoff, fails fast on 4xx (except 408/429)."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    last: Optional[Exception] = None
    status: Optional[int] = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last, status = e, e.code
            if 400 <= e.code < 500 and e.code not in (408, 429):
                break
        except (urllib.error.URLError, OSError) as e:  # includes timeouts
            last, status = e, None
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    raise NetworkError(f"GET {url} failed: {last}", status)


def _cache_path(root: Path, url: str) -> Path:
    """Short cache layout, e.g. ``annual/crops/recent/<file>``, ``help/<file>``."""
    path = urllib.parse.urlsplit(url).path
    for marker in ("/observations_germany/phenology/", "/climate_environment/CDC/"):
        if marker in path:
            path = path.split(marker, 1)[1]
            break
    path = path.strip("/").replace("_reporters/", "/", 1)
    if url.endswith("/"):
        path += "/_index.html"
    p = root.absolute().joinpath(*path.split("/"))
    if sys.platform.startswith("win") and len(str(p)) > 240 and not str(p).startswith("\\\\?\\"):
        p = Path("\\\\?\\" + str(p))   # extended-length path, beyond MAX_PATH
    return p


def never_expires(url: str) -> bool:
    """Historical data files are immutable; everything else is refreshed."""
    return url.endswith("_hist.txt")


def fetch(url: str, *, cache: CacheArg = None, offline: bool = False,
          max_age_days: float = 1.0) -> bytes:
    """Return the bytes at ``url``, going through the on-disk cache."""
    root = cache_dir(cache)
    if root is None:
        if offline:
            raise NetworkError(f"offline and cache disabled: {url}")
        return _get(url)
    f = _cache_path(root, url)
    gone = f.with_name(f.name + ".404")   # remembered "not found" (e.g. an absent folder)
    max_age = max_age_days * 86400.0
    if f.exists() and (offline or never_expires(url) or time.time() - f.stat().st_mtime < max_age):
        return f.read_bytes()
    if gone.exists() and (offline or time.time() - gone.stat().st_mtime < max_age):
        raise NetworkError(f"not found (cached): {url}", 404)
    if offline:
        raise NetworkError(f"offline: not in cache: {url}", 404)
    try:
        data = _get(url)
    except NetworkError as e:
        if e.status in (404, 410):
            gone.parent.mkdir(parents=True, exist_ok=True)
            gone.touch()
        elif f.exists():
            warnings.warn(f"{e}; using stale cached copy {f}", RuntimeWarning, stacklevel=2)
            return f.read_bytes()
        raise
    if gone.exists():
        gone.unlink()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + f".part{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, f)
    return data
