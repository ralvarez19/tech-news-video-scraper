"""exporter.py — genera las carpetas de salida y los archivos por noticia.

Estructura:
  output/YYYY-MM-DD_HH-mm-ss/
      noticia_01/
          noticia.json
          noticia.txt
          card.html
          embed.html
          source.url
          video.url
          metadata.json
          README.txt
      noticia_02/
      ...

card.html se renderiza con Jinja2 a partir de templates/card.html.
embed.html es un reproductor mínimo independiente.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Article
from .utils import get_logger, run_timestamp

log = get_logger()


class Exporter:
    def __init__(self, settings: dict, templates_dir: str = "templates"):
        out = (settings or {}).get("output", {})
        self.base_dir = Path(out.get("base_dir", "output"))
        self.prefix = out.get("folder_prefix", "noticia_")
        self.templates_dir = Path(templates_dir)
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )

    def make_run_dir(self) -> Path:
        run_dir = self.base_dir / run_timestamp()
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    # ------------------------------------------------------------------ #
    def export_article(self, run_dir: Path, index: int, article: Article) -> Path:
        folder = run_dir / f"{self.prefix}{index:02d}"
        folder.mkdir(parents=True, exist_ok=True)

        carousel = article.carousel_text or self._build_carousel_text(article)
        article.carousel_text = carousel
        article.output_folder = str(folder)

        # --- noticia.json (objeto completo) ---
        (folder / "noticia.json").write_text(
            json.dumps(article.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8")

        # --- metadata.json (subconjunto + ranking) ---
        meta = {
            "title_es": article.title_es,
            "title_original": article.title_original,
            "language_original": article.language_original,
            "source_name": article.source_name,
            "region": article.region,
            "published_at": article.published_at,
            "scraped_at": article.scraped_at,
            "article_url": article.article_url,
            "canonical_url": article.canonical_url,
            "video_url": article.video_url,
            "video_embed_url": article.video_embed_url,
            "video_type": article.video_type,
            "score": article.score,
            "score_breakdown": article.score_breakdown,
            "status": article.status,
        }
        (folder / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # --- noticia.txt (formato pedido) ---
        (folder / "noticia.txt").write_text(self._txt(article), encoding="utf-8")

        # --- card.html (descripción arriba, video abajo) ---
        (folder / "card.html").write_text(self._render_card(article), encoding="utf-8")

        # --- embed.html (reproductor mínimo) ---
        (folder / "embed.html").write_text(self._render_embed(article), encoding="utf-8")

        # --- source.url y video.url (accesos directos de Windows) ---
        (folder / "source.url").write_text(
            f"[InternetShortcut]\nURL={article.article_url}\n", encoding="utf-8")
        if article.video_url or article.video_embed_url:
            (folder / "video.url").write_text(
                f"[InternetShortcut]\nURL={article.video_url or article.video_embed_url}\n",
                encoding="utf-8")
        else:
            (folder / "video.url").write_text("[InternetShortcut]\nURL=\n", encoding="utf-8")

        # --- README.txt ---
        (folder / "README.txt").write_text(self._readme(index, article), encoding="utf-8")

        return folder

    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_carousel_text(article: Article) -> str:
        base = article.summary_es or article.title_es or article.title_original
        base = base.strip()
        if len(base) > 180:
            base = base[:177].rstrip() + "..."
        return base

    @staticmethod
    def _txt(a: Article) -> str:
        return (
            f"Título: {a.title_es or a.title_original}\n"
            f"Descripción corta: {a.summary_es or a.summary_original}\n"
            f"Fuente: {a.source_name} ({a.region})\n"
            f"Fecha: {a.published_at or 'N/D'}\n"
            f"Link noticia: {a.article_url}\n"
            f"Link video: {a.video_url or a.video_embed_url or 'N/D'}\n"
            f"Texto para carrusel: {a.carousel_text}\n"
        )

    def _render_card(self, a: Article) -> str:
        try:
            tpl = self.env.get_template("card.html")
            return tpl.render(
                title_es=a.title_es or a.title_original,
                summary_es=a.summary_es or a.summary_original,
                source_name=a.source_name,
                region=a.region,
                published=(a.published_at or "")[:10],
                article_url=a.article_url,
                video_embed_url=a.video_embed_url,
                video_url=a.video_url,
                video_type=a.video_type,
                carousel_text=a.carousel_text,
            )
        except Exception as exc:
            log.warning(f"No se pudo renderizar card.html ({exc}); se usa fallback.")
            return self._render_embed(a)

    @staticmethod
    def _render_embed(a: Article) -> str:
        embed = a.video_embed_url or a.video_url or ""
        title = a.title_es or a.title_original
        summary = a.summary_es or a.summary_original
        if a.video_type == "html5" and a.video_url:
            player = f'<video controls preload="metadata" src="{a.video_url}" style="width:100%;height:100%"></video>'
        elif embed:
            player = (f'<iframe src="{embed}" allow="autoplay; encrypted-media; '
                      f'picture-in-picture" allowfullscreen '
                      f'style="width:100%;height:100%;border:0"></iframe>')
        else:
            player = '<div style="color:#999;text-align:center;padding-top:40%">Sin video</div>'
        return (
            "<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            f"<title>{title}</title>"
            "<style>body{margin:0;background:#000;font-family:system-ui}"
            ".wrap{max-width:900px;margin:0 auto}"
            ".desc{color:#fff;padding:16px;font-size:18px;background:#111}"
            ".v{position:relative;padding-top:56.25%}"
            ".v>*{position:absolute;inset:0;width:100%;height:100%}</style></head>"
            f"<body><div class='wrap'><div class='desc'>{summary or title}</div>"
            f"<div class='v'>{player}</div></div></body></html>"
        )

    @staticmethod
    def _readme(index: int, a: Article) -> str:
        return (
            f"NOTICIA {index:02d}\n"
            f"==================================================\n\n"
            f"Contenido de esta carpeta:\n"
            f"  - noticia.json   : objeto completo de la noticia (todos los campos).\n"
            f"  - noticia.txt    : resumen legible (título, descripción, links...).\n"
            f"  - card.html      : tarjeta vertical (descripción arriba, video abajo).\n"
            f"                     Ábrela en el navegador y captúrala para redes.\n"
            f"  - embed.html     : reproductor mínimo del video.\n"
            f"  - metadata.json  : metadatos + puntuación del ranking.\n"
            f"  - source.url     : acceso directo a la noticia original.\n"
            f"  - video.url      : acceso directo al video.\n\n"
            f"Título: {a.title_es or a.title_original}\n"
            f"Fuente: {a.source_name} ({a.region})\n"
            f"Puntuación: {a.score}  Detalle: {a.score_breakdown}\n"
            f"Video: {a.video_type or 'N/D'} -> {a.video_url or a.video_embed_url or 'N/D'}\n"
        )
