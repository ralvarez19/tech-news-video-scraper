"""app.py — Tech News Video Scraper + generador de carruseles visuales.

Busca noticias recientes de tecnología/IA, prioriza las que tienen VIDEO,
completa con noticias de IMAGEN de alta calidad si hace falta, y genera por cada
una un slide.png 1080x1350 listo para carrusel (estilo tecnológico/premium),
además de card.html, embed.html, poster/hero, metadata y la galería index.html.

Uso:
    python app.py
    python app.py --topic "robótica" --num 5 --lang es --no-input

Respeta robots.txt; no salta paywalls/captchas/DRM. Si un video no es embebible,
NO falla: guarda el enlace + poster y usa la imagen en el slide.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.utils import load_yaml, setup_logging
from src.models import Run, Article
from src.database import Database
from src.source_loader import load_sources
from src.scraper import Scraper
from src.translator import Translator
from src.ranker import Ranker
from src.card_renderer import CardRenderer
from src.exporter import Exporter

try:
    from rich.table import Table
    from rich.console import Console
    _console = Console()
except Exception:  # pragma: no cover
    _console = None

SETTINGS_PATH = "config/settings.yaml"
SOURCES_PATH = "config/sources.yaml"


# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Tech News Video Scraper")
    p.add_argument("--topic", help="Tema de búsqueda")
    p.add_argument("--num", type=int, help="Número de noticias a generar")
    p.add_argument("--lang", help="Idioma de salida (por defecto es)")
    p.add_argument("--no-input", action="store_true",
                   help="No preguntar; usar valores por defecto/flags")
    return p.parse_args()


def ask_inputs(args, settings) -> tuple[str, int, str]:
    d = settings.get("defaults", {})
    def_topic = d.get("topic", "tecnología, inteligencia artificial y avances tecnológicos")
    def_num = int(d.get("num_news", 5))
    def_lang = d.get("language", "es")

    if args.no_input:
        return (args.topic or def_topic, args.num or def_num, args.lang or def_lang)

    if args.topic:
        topic = args.topic
    else:
        try:
            entered = input("¿Qué tema quieres buscar? Presiona ENTER para usar "
                            "tecnología e inteligencia artificial por defecto: ").strip()
        except EOFError:
            entered = ""
        topic = entered or def_topic

    if args.num:
        num = args.num
    else:
        try:
            raw = input(f"¿Cuántas noticias quieres? (ENTER = {def_num}): ").strip()
        except EOFError:
            raw = ""
        num = int(raw) if raw.isdigit() and int(raw) > 0 else def_num

    if args.lang:
        lang = args.lang
    else:
        try:
            raw = input(f"Idioma de salida (ENTER = {def_lang}): ").strip()
        except EOFError:
            raw = ""
        lang = raw or def_lang

    return topic, num, lang


# --------------------------------------------------------------------------- #
def _short_headline(title: str, limit: int = 85) -> str:
    title = (title or "").strip()
    if len(title) <= limit:
        return title
    cut = title[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + "…"


def _short_caption(summary: str, limit: int = 220) -> str:
    summary = (summary or "").strip()
    if len(summary) <= limit:
        return summary
    cut = summary[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + "…"


# --------------------------------------------------------------------------- #
def run() -> int:
    args = parse_args()
    settings = load_yaml(SETTINGS_PATH)
    log = setup_logging(settings.get("logging", {}).get("level", "INFO"))

    topic, num_target, lang = ask_inputs(args, settings)
    log.info(f"[bold cyan]Tema:[/] {topic}  |  [bold]Noticias:[/] {num_target}  |  "
             f"[bold]Idioma:[/] {lang}")

    fallback_to_image = settings.get("video", {}).get("fallback_to_image", True)

    db = Database(settings.get("database", {}).get("path", "data/news.db"))
    sources = load_sources(SOURCES_PATH, only_enabled=True)
    for s in sources:
        db.upsert_source(s.name, s.trusted, s.region, s.enabled)

    scraper = Scraper(settings)
    translator = Translator(settings)
    ranker = Ranker(settings)
    renderer = CardRenderer(settings)
    exporter = Exporter(settings, renderer=renderer, session=scraper.session)

    run_obj = Run(topic=topic, language=lang, requested=num_target)
    run_id = db.start_run(run_obj)

    discarded_no_media = 0
    skipped_duplicates = 0
    video_candidates: list[Article] = []
    image_candidates: list[Article] = []
    seen_in_run: set[str] = set()

    pool_target = max(num_target * 4, num_target + 8)

    # ---------------------- Recolección ---------------------- #
    for source in sources:
        if len(video_candidates) >= pool_target:
            break
        log.info(f"[bold]Fuente:[/] {source.name}")
        try:
            urls = scraper.collect_article_urls(source)
        except Exception as exc:
            log.warning(f"  No se pudieron listar artículos de {source.name}: {exc}")
            continue
        log.info(f"  {len(urls)} enlaces candidatos")

        for url in urls:
            if len(video_candidates) >= pool_target:
                break
            try:
                article = scraper.fetch_article(url, source, topic)
            except Exception as exc:
                log.debug(f"  Error procesando {url}: {exc}")
                continue
            if article is None:
                continue

            # Necesitamos al menos video o imagen para un slide decente
            if article.media_type == "none":
                discarded_no_media += 1
                continue

            if db.is_duplicate(article):
                skipped_duplicates += 1
                continue
            key = article.canonical_url or article.article_url
            if key in seen_in_run:
                skipped_duplicates += 1
                continue
            seen_in_run.add(key)

            ranker.score(article, trusted=source.trusted, is_duplicate=False,
                         published_dt=getattr(article, "_published_dt", None))
            if not ranker.passes(article):
                continue

            if article.media_type == "video":
                video_candidates.append(article)
                log.info(f"  [green]✓ VIDEO[/] (score {article.score}): "
                         f"{article.title_original[:64]}")
            else:
                image_candidates.append(article)
                log.info(f"  [cyan]✓ imagen[/] (score {article.score}): "
                         f"{article.title_original[:64]}")

    scraper.close()

    # ---------------------- Selección ---------------------- #
    best_video = Ranker.sort_best(video_candidates)
    selected = best_video[:num_target]
    if len(selected) < num_target and fallback_to_image:
        need = num_target - len(selected)
        fillers = Ranker.sort_best(image_candidates)[:need]
        if fillers:
            log.info(f"[yellow]Solo {len(selected)} con video; completando con "
                     f"{len(fillers)} de imagen de alta calidad.[/]")
        selected += fillers

    # ---------------------- Traducción + export ---------------------- #
    run_dir = exporter.make_run_dir()
    final: list[Article] = []
    items: list[dict] = []
    embed_blocked = with_video = with_image = 0

    for i, article in enumerate(selected, start=1):
        src_lang = article.language_original
        if lang.startswith("es"):
            article.title_es = translator.translate(article.title_original, src_lang)
            article.summary_es = translator.translate(article.summary_original, src_lang)
        else:
            article.title_es = article.title_original
            article.summary_es = article.summary_original
        article.short_headline_es = _short_headline(article.title_es or article.title_original)
        article.short_caption_es = _short_caption(article.summary_es or article.summary_original)

        article.run_id = run_id
        article.status = "selected"
        try:
            db.insert_article(article)
        except Exception as exc:
            log.warning(f"No se pudo guardar en BD: {exc}")

        item = exporter.export_article(run_dir, i, article)
        article.status = "exported"
        final.append(article)
        items.append(item)

        if article.media_type == "video":
            with_video += 1
        else:
            with_image += 1
        if article.embed_status == "blocked":
            embed_blocked += 1

        log.info(f"[green]Exportada[/] noticia_{i:02d} "
                 f"[{article.media_type}/{article.embed_status}] -> {item.get('folder')}")

    renderer.close()

    stats = {
        "requested": num_target, "found": len(final),
        "with_video": with_video, "with_image": with_image,
        "embed_blocked": embed_blocked, "discarded_no_media": discarded_no_media,
        "skipped_duplicates": skipped_duplicates,
    }
    exporter.finalize_run(run_dir, run_id, topic, items, stats)
    db.finish_run(run_id, len(final), discarded_no_media, skipped_duplicates, str(run_dir))
    db.close()

    print_summary(topic, run_dir, stats, final, log)
    return 0


# --------------------------------------------------------------------------- #
def print_summary(topic, run_dir, stats, final, log) -> None:
    log.info("")
    log.info("[bold green]==================== RESUMEN ====================[/]")
    log.info(f"Carpeta creada:                 {run_dir}")
    log.info(f"Galería:                        {run_dir / 'index.html'}")
    log.info(f"Noticias generadas:             {stats['found']} / {stats['requested']}")
    log.info(f"  · con video:                  {stats['with_video']}")
    log.info(f"  · con imagen (fallback):      {stats['with_image']}")
    log.info(f"Embeds bloqueados (poster usado): {stats['embed_blocked']}")
    log.info(f"Descartadas sin media:          {stats['discarded_no_media']}")
    log.info(f"Repetidas saltadas:             {stats['skipped_duplicates']}")
    if stats['found'] < stats['requested']:
        log.info(f"[yellow]Faltaron {stats['requested'] - stats['found']} noticias.[/]")

    if _console and final:
        table = Table(title="Noticias finales", show_lines=False)
        table.add_column("#", justify="right", style="cyan")
        table.add_column("Titular (ES)", style="white", overflow="fold")
        table.add_column("Fuente", style="green")
        table.add_column("Media", style="magenta")
        table.add_column("Embed", style="yellow")
        table.add_column("Score", justify="right")
        table.add_column("slide.png", justify="center")
        for i, a in enumerate(final, start=1):
            table.add_row(str(i),
                          (a.short_headline_es or a.title_es or a.title_original)[:60],
                          a.source_name, a.media_type, a.embed_status, str(a.score),
                          "✓" if a.local_slide_path else "—")
        _console.print(table)

    log.info("")
    log.info("[bold]Rutas de cada carpeta:[/]")
    for i, a in enumerate(final, start=1):
        log.info(f"  noticia_{i:02d}: {a.output_folder}")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    try:
        raise SystemExit(run())
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
        raise SystemExit(130)
