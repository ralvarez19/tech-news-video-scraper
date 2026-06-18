"""source_loader.py — carga y valida las fuentes de config/sources.yaml."""
from __future__ import annotations

from pathlib import Path

from .models import Source
from .utils import load_yaml, get_logger

log = get_logger()


def load_sources(path: str = "config/sources.yaml", only_enabled: bool = True) -> list[Source]:
    """Lee sources.yaml y devuelve una lista de objetos Source.

    Las fuentes confiables (trusted=True) se ordenan primero, para
    "intentar primero fuentes confiables".
    """
    data = load_yaml(path)
    raw = data.get("sources", []) if isinstance(data, dict) else []
    sources: list[Source] = []

    for item in raw:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        src = Source.from_dict(item)
        if only_enabled and not src.enabled:
            continue
        # Una fuente es útil solo si tiene RSS o algún listing_url.
        if not src.rss and not src.listing_urls:
            log.warning(f"[yellow]Fuente sin RSS ni listing_urls, se omite:[/] {src.name}")
            continue
        sources.append(src)

    # Confiables primero; dentro de cada grupo se mantiene el orden del archivo.
    sources.sort(key=lambda s: (not s.trusted))

    if not sources:
        log.warning("No se cargó ninguna fuente válida desde sources.yaml")
    else:
        log.info(f"Fuentes cargadas: {len(sources)} "
                 f"({sum(1 for s in sources if s.trusted)} confiables)")
    return sources
