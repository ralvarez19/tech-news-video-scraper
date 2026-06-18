"""models.py — estructuras de datos del proyecto (dataclasses).

Pensadas para ser fáciles de serializar a JSON y de mapear a la base de datos,
y para poder reutilizarse luego desde una API FastAPI o una app Flutter.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional


@dataclass
class Source:
    """Una fuente de noticias configurada en sources.yaml."""
    name: str
    enabled: bool = True
    trusted: bool = False
    region: str = "Global"
    listing_urls: list[str] = field(default_factory=list)
    rss: Optional[str] = None
    article_pattern: Optional[str] = None
    needs_js: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "Source":
        return cls(
            name=d.get("name", "Desconocida"),
            enabled=bool(d.get("enabled", True)),
            trusted=bool(d.get("trusted", False)),
            region=d.get("region", "Global"),
            listing_urls=list(d.get("listing_urls", []) or []),
            rss=d.get("rss"),
            article_pattern=d.get("article_pattern"),
            needs_js=bool(d.get("needs_js", False)),
        )


@dataclass
class VideoInfo:
    """Información del video detectado en un artículo."""
    found: bool = False
    video_type: Optional[str] = None        # youtube | vimeo | html5 | og_video | jsonld | iframe ...
    video_url: Optional[str] = None         # URL "pública" del video (página/watch)
    video_embed_url: Optional[str] = None   # URL para embeber en un iframe
    related: bool = True                    # ¿parece directamente relacionado con la noticia?


@dataclass
class Article:
    """Una noticia procesada, lista para guardar y exportar."""
    # Identificación
    run_id: Optional[int] = None
    topic: str = ""

    # Contenido (original + traducido)
    title_original: str = ""
    title_es: str = ""
    summary_original: str = ""
    summary_es: str = ""
    language_original: str = "und"

    # Textos cortos para la pieza visual
    short_headline_es: str = ""   # titular corto en MAYÚSCULAS para el slide
    short_caption_es: str = ""    # descripción de 2-4 líneas para el slide

    # Fuente / enlaces
    source_name: str = ""
    source_url: str = ""        # URL de la fuente (listado/portada)
    article_url: str = ""       # URL del artículo
    canonical_url: str = ""     # URL canónica/limpia del artículo

    # Video
    video_url: Optional[str] = None
    video_embed_url: Optional[str] = None
    video_type: Optional[str] = None
    embed_status: str = "none"  # ok | blocked | none  (¿se puede embeber el video?)

    # Imagen / media
    media_type: str = "none"            # video | image | none
    hero_image_url: Optional[str] = None
    video_poster_url: Optional[str] = None
    local_slide_path: Optional[str] = None   # ruta a slide.png
    local_media_path: Optional[str] = None   # ruta a hero_image.jpg / video_poster.jpg

    # Metadatos
    region: str = "Global"
    country: str = ""
    published_at: Optional[str] = None   # ISO 8601
    scraped_at: Optional[str] = None     # ISO 8601
    content_hash: str = ""
    status: str = "candidate"            # candidate | selected | exported | skipped_duplicate | no_video
    output_folder: Optional[str] = None

    # Ranking / texto carrusel (no se persisten todos en DB, pero viajan en el objeto)
    score: int = 0
    score_breakdown: dict = field(default_factory=dict)
    carousel_text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    # ---- Mapeo a/desde la tabla articles -------------------------------- #
    DB_COLUMNS = [
        "run_id", "topic", "title_original", "title_es", "summary_original",
        "summary_es", "short_headline_es", "short_caption_es",
        "language_original", "source_name", "source_url", "article_url",
        "canonical_url", "video_url", "video_embed_url", "video_type",
        "embed_status", "media_type", "hero_image_url", "video_poster_url",
        "local_slide_path", "local_media_path", "region", "country",
        "published_at", "scraped_at", "content_hash", "status", "output_folder",
    ]

    def to_db_row(self) -> dict:
        d = self.to_dict()
        return {k: d.get(k) for k in self.DB_COLUMNS}


@dataclass
class Run:
    """Una ejecución del programa."""
    id: Optional[int] = None
    topic: str = ""
    language: str = "es"
    requested: int = 5
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    found: int = 0
    discarded_no_video: int = 0
    skipped_duplicates: int = 0
    output_dir: Optional[str] = None
