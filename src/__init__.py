"""Tech News Video Scraper — paquete principal.

Módulos:
    database       Capa SQLite (esquema + acceso a datos + deduplicación).
    models         Dataclasses (Article, Source, Run).
    source_loader  Carga y valida config/sources.yaml.
    scraper        Descarga listados y artículos (requests/BS4 + Playwright opcional).
    video_detector Detecta video en el HTML de un artículo.
    translator     Traducción modular al español (API opcional + fallback).
    ranker         Sistema de puntuación para elegir las mejores noticias.
    exporter       Genera las carpetas de salida y archivos por noticia.
    utils          Utilidades: hashing, fechas, logging, normalización.
"""

__version__ = "1.0.0"
