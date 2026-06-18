"""utils.py — utilidades compartidas.

Incluye:
  - Carga de YAML de configuración.
  - Logging con rich (consola bonita) y fallback a logging estándar.
  - Hashing y normalización de títulos / URLs (para deduplicación).
  - Parsing flexible de fechas.
  - Helpers de URL (canonicalización).
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import yaml

try:  # rich es opcional pero recomendado
    from rich.console import Console
    from rich.logging import RichHandler
    _HAS_RICH = True
    console = Console()
except Exception:  # pragma: no cover
    _HAS_RICH = False
    console = None


# --------------------------------------------------------------------------- #
# Configuración / logging
# --------------------------------------------------------------------------- #
def load_yaml(path: str | Path) -> dict[str, Any]:
    """Carga un archivo YAML y devuelve un dict (vacío si no existe)."""
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data or {}


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configura el logger raíz del proyecto."""
    lvl = getattr(logging, str(level).upper(), logging.INFO)
    logger = logging.getLogger("tnvs")
    logger.setLevel(lvl)
    logger.handlers.clear()

    if _HAS_RICH:
        handler: logging.Handler = RichHandler(
            console=console, rich_tracebacks=True, show_path=False, markup=True
        )
        fmt = "%(message)s"
    else:
        handler = logging.StreamHandler()
        fmt = "%(asctime)s [%(levelname)s] %(message)s"

    handler.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("tnvs")


# --------------------------------------------------------------------------- #
# Normalización y hashing
# --------------------------------------------------------------------------- #
def normalize_title(title: str) -> str:
    """Normaliza un título para comparar duplicados.

    - minúsculas
    - sin acentos
    - sin signos de puntuación
    - espacios colapsados
    """
    if not title:
        return ""
    txt = unicodedata.normalize("NFKD", title)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    txt = txt.lower()
    txt = re.sub(r"[^a-z0-9\s]", " ", txt)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def title_hash(title: str) -> str:
    """Hash estable del título normalizado (para deduplicar)."""
    return hashlib.sha256(normalize_title(title).encode("utf-8")).hexdigest()


def content_hash(*parts: str) -> str:
    """Hash de contenido a partir de varias piezas (título + url + video...)."""
    joined = "||".join(normalize_title(p) if p else "" for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# URLs
# --------------------------------------------------------------------------- #
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref", "cmpid",
    "ito", "at_medium", "at_campaign",
}


def canonical_url(url: str) -> str:
    """Devuelve una versión canónica/limpia de la URL.

    - quita parámetros de tracking
    - quita fragmento (#...)
    - normaliza esquema y host en minúsculas
    - elimina barra final redundante
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return url.strip()

    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    query_pairs = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(query_pairs)

    return urlunparse((scheme, netloc, path, "", query, ""))


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def absolutize(base_url: str, maybe_relative: str) -> str:
    """Convierte una URL relativa en absoluta respecto a base_url."""
    from urllib.parse import urljoin
    if not maybe_relative:
        return ""
    return urljoin(base_url, maybe_relative)


# --------------------------------------------------------------------------- #
# Fechas
# --------------------------------------------------------------------------- #
def parse_date(value: Optional[str]) -> Optional[datetime]:
    """Parsea una fecha en muchos formatos. Devuelve datetime con tz UTC o None."""
    if not value:
        return None
    value = value.strip()
    try:
        from dateutil import parser as dateparser
        dt = dateparser.parse(value)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def age_in_days(dt: Optional[datetime]) -> Optional[float]:
    if not dt:
        return None
    return (now_utc() - dt).total_seconds() / 86400.0


def run_timestamp() -> str:
    """Marca de tiempo para nombre de carpeta: YYYY-MM-DD_HH-mm-ss."""
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
