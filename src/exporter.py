"""exporter.py — genera las carpetas de salida, los assets visuales y la galería.

Por cada noticia produce:
    slide.png          (OBLIGATORIO — pieza visual final del carrusel)
    card.html          (HTML usado para el slide)
    embed.html         (reproductor / fallback a poster)
    video_poster.jpg   (si hay poster de video)
    hero_image.jpg     (si hay imagen principal)
    metadata.json, noticia.json, noticia.txt
    source.url, video.url, video_url.txt
    README.txt

En la raíz del run:
    index.html (galería), summary.json, summary.txt
"""
from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Optional

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Article
from .card_renderer import CardRenderer
from .media_extractor import check_embeddable, download_image, youtube_thumbnail
from .utils import get_logger, run_timestamp, now_utc, iso

log = get_logger()


def _img_data_uri(path: Optional[Path]) -> Optional[str]:
    if not path or not Path(path).exists():
        return None
    mime = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    b64 = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


class Exporter:
    def __init__(self, settings: dict, renderer: Optional[CardRenderer] = None,
                 session: Optional[requests.Session] = None,
                 templates_dir: str = "templates"):
        out = (settings or {}).get("output", {})
        vid = (settings or {}).get("video", {})
        self.base_dir = Path(out.get("base_dir", "output"))
        self.prefix = out.get("folder_prefix", "noticia_")
        self.check_embed = vid.get("check_embeddable", True)
        self.download_media = vid.get("download_media", True)
        self.templates_dir = Path(templates_dir)
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        self.renderer = renderer or CardRenderer(settings, templates_dir)
        self.session = session or requests.Session()

    def make_run_dir(self) -> Path:
        run_dir = self.base_dir / run_timestamp()
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    # ================================================================== #
    def export_article(self, run_dir: Path, index: int, article: Article) -> dict:
        folder = run_dir / f"{self.prefix}{index:02d}"
        folder.mkdir(parents=True, exist_ok=True)

        # --- 1) Descargar media (poster y/o hero image) ----------------- #
        poster_path: Optional[Path] = None
        hero_path: Optional[Path] = None

        if self.download_media:
            if article.media_type == "video":
                poster_src = (article.video_poster_url
                              or youtube_thumbnail(article.video_url or ""))
                if poster_src:
                    p = folder / "video_poster.jpg"
                    if download_image(poster_src, p, self.session):
                        poster_path = p
            if article.hero_image_url:
                h = folder / "hero_image.jpg"
                if download_image(article.hero_image_url, h, self.session):
                    hero_path = h

        # Imagen para el slide: poster (video) > hero > None
        slide_image = poster_path or hero_path
        if slide_image:
            article.local_media_path = str(slide_image)

        # --- 2) ¿El video es embebible? -------------------------------- #
        if article.media_type == "video" and (article.video_embed_url or article.video_url):
            if self.check_embed:
                ok, reason = check_embeddable(
                    article.video_embed_url or article.video_url, self.session)
                article.embed_status = "ok" if ok else "blocked"
                article._embed_reason = reason  # type: ignore
            else:
                article.embed_status = "ok"
        else:
            article.embed_status = "none"

        # --- 3) Render del slide.png (OBLIGATORIO) ---------------------- #
        slide_png = folder / "slide.png"
        created = self.renderer.render_slide(article, str(slide_image) if slide_image else None,
                                             slide_png)
        if created:
            article.local_slide_path = str(slide_png)
        else:
            log.warning(f"[red]No se pudo crear slide.png para noticia_{index:02d}[/]")

        article.output_folder = str(folder)
        article.carousel_text = article.short_caption_es or article.summary_es or ""

        # --- 4) Archivos de datos -------------------------------------- #
        (folder / "noticia.json").write_text(
            json.dumps(article.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "metadata.json").write_text(
            json.dumps(self._metadata(article), ensure_ascii=False, indent=2), encoding="utf-8")
        (folder / "noticia.txt").write_text(self._txt(article), encoding="utf-8")
        (folder / "embed.html").write_text(self._render_embed(article, poster_path), encoding="utf-8")
        (folder / "source.url").write_text(
            f"[InternetShortcut]\nURL={article.article_url}\n", encoding="utf-8")
        vurl = article.video_url or article.video_embed_url or ""
        (folder / "video.url").write_text(f"[InternetShortcut]\nURL={vurl}\n", encoding="utf-8")
        # video_url.txt explícito (caso B: video no embebible)
        (folder / "video_url.txt").write_text(vurl + ("\n" if vurl else ""), encoding="utf-8")
        (folder / "README.txt").write_text(self._readme(index, article), encoding="utf-8")

        return self._index_item(folder, run_dir, article)

    # ================================================================== #
    def finalize_run(self, run_dir: Path, run_id, topic: str, items: list[dict],
                     stats: dict) -> None:
        # index.html
        try:
            tpl = self.env.get_template("index_template.html")
            html = tpl.render(run_id=run_id, topic=topic,
                              generated_at=iso(now_utc())[:19].replace("T", " "),
                              items=items,
                              intro_rel=stats.get("intro_rel", ""))
            (run_dir / "index.html").write_text(html, encoding="utf-8")
        except Exception as exc:
            log.warning(f"No se pudo generar index.html: {exc}")

        # summary.json
        summary = {
            "run_id": run_id,
            "topic": topic,
            "generated_at": iso(now_utc()),
            "output_dir": str(run_dir),
            "intro_path": stats.get("intro_path", ""),
            "stats": stats,
            "items": items,
        }
        (run_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

        # summary.txt
        lines = [
            f"Run: {run_id}",
            f"Tema: {topic}",
            f"Carpeta: {run_dir}",
            f"Intro diaria: {stats.get('intro_path') or 'N/D'}",
            f"Noticias generadas: {stats.get('found')}/{stats.get('requested')}",
            f"Con video: {stats.get('with_video')}  |  Con imagen: {stats.get('with_image')}",
            f"Embeds bloqueados: {stats.get('embed_blocked')}",
            f"Descartadas sin media: {stats.get('discarded_no_media')}",
            f"Repetidas saltadas: {stats.get('skipped_duplicates')}",
            "",
            "Noticias:",
        ]
        for i, it in enumerate(items, 1):
            lines.append(f"  {i:02d}. [{it['media_type']}] {it['title']}  "
                         f"({it['source_name']})")
        (run_dir / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ================================================================== #
    @staticmethod
    def _metadata(a: Article) -> dict:
        return {
            "title_es": a.title_es, "title_original": a.title_original,
            "short_headline_es": a.short_headline_es,
            "short_caption_es": a.short_caption_es,
            "summary_es": a.summary_es,
            "language_original": a.language_original,
            "source_name": a.source_name, "country": a.country, "region": a.region,
            "published_at": a.published_at, "scraped_at": a.scraped_at,
            "article_url": a.article_url, "canonical_url": a.canonical_url,
            "media_type": a.media_type,
            "video_url": a.video_url, "video_embed_url": a.video_embed_url,
            "video_type": a.video_type, "embed_status": a.embed_status,
            "embed_reason": getattr(a, "_embed_reason", None),
            "hero_image_url": a.hero_image_url, "video_poster_url": a.video_poster_url,
            "local_slide_path": a.local_slide_path, "local_media_path": a.local_media_path,
            "score": a.score, "score_breakdown": a.score_breakdown,
            "status": a.status,
        }

    @staticmethod
    def _txt(a: Article) -> str:
        return (
            f"Título: {a.title_es or a.title_original}\n"
            f"Titular corto: {a.short_headline_es}\n"
            f"Descripción corta: {a.short_caption_es or a.summary_es or a.summary_original}\n"
            f"Fuente: {a.source_name} ({a.region})\n"
            f"Fecha: {a.published_at or 'N/D'}\n"
            f"Tipo de media: {a.media_type}\n"
            f"Estado embed: {a.embed_status}\n"
            f"Link noticia: {a.article_url}\n"
            f"Link video: {a.video_url or a.video_embed_url or 'N/D'}\n"
            f"Slide: {a.local_slide_path or 'N/D'}\n"
        )

    def _render_embed(self, a: Article, poster_path: Optional[Path]) -> str:
        try:
            tpl = self.env.get_template("embed_template.html")
            return tpl.render(
                title=a.title_es or a.title_original,
                caption=a.short_caption_es or a.summary_es or a.summary_original,
                embed_status=a.embed_status,
                video_embed_url=a.video_embed_url,
                video_url=a.video_url,
                video_type=a.video_type,
                poster_data_uri=_img_data_uri(poster_path),
                article_url=a.article_url,
                source_name=a.source_name,
            )
        except Exception as exc:
            log.debug(f"embed_template falló ({exc})")
            return f"<!doctype html><meta charset=utf-8><p>{a.title_original}</p>"

    @staticmethod
    def _readme(index: int, a: Article) -> str:
        reason = getattr(a, "_embed_reason", None)
        return (
            f"NOTICIA {index:02d}\n{'='*50}\n\n"
            f"slide.png        : pieza visual final 1080x1350 para el carrusel.\n"
            f"card.html        : HTML usado para generar el slide.\n"
            f"embed.html       : reproductor del video (o fallback a poster).\n"
            f"video_poster.jpg : miniatura del video (si existe).\n"
            f"hero_image.jpg   : imagen principal del artículo (si existe).\n"
            f"metadata.json    : metadatos + ranking + estado del embed.\n"
            f"noticia.json     : objeto completo.\n"
            f"noticia.txt      : resumen legible.\n"
            f"source.url       : acceso directo al artículo.\n"
            f"video.url / video_url.txt : enlace directo al video.\n\n"
            f"Título: {a.title_es or a.title_original}\n"
            f"Fuente: {a.source_name} ({a.region})\n"
            f"Tipo de media: {a.media_type}\n"
            f"Estado embed: {a.embed_status}"
            + (f" (motivo: {reason})" if reason else "") + "\n"
            f"Video: {a.video_type or 'N/D'} -> {a.video_url or a.video_embed_url or 'N/D'}\n"
            f"Puntuación: {a.score}  Detalle: {a.score_breakdown}\n"
        )

    @staticmethod
    def _index_item(folder: Path, run_dir: Path, a: Article) -> dict:
        slide_rel = (str((folder / "slide.png").relative_to(run_dir)).replace("\\", "/")
                     if a.local_slide_path else "")
        embed_rel = f"{folder.name}/embed.html"
        return {
            "folder": folder.name,
            "slide_rel": slide_rel,
            "title": a.title_es or a.title_original,
            "source_name": a.source_name,
            "date": (a.published_at or "")[:10],
            "media_type": a.media_type,
            "embed_status": a.embed_status,
            "article_url": a.article_url,
            "video_url": a.video_url or a.video_embed_url or "",
            "has_embed": a.media_type == "video",
            "embed_rel": embed_rel,
        }
