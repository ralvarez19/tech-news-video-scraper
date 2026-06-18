"""app.py — Tech News Video Scraper (MVP local para Windows).

Busca noticias recientes de tecnología/IA con video, las puntúa, guarda en
SQLite y exporta carpetas listas para publicar como carrusel.

Uso:
    python app.py
    python app.py --topic "robótica" --num 5 --lang es
    python app.py --no-input            # usa valores por defecto sin preguntar

Respeta robots.txt, no salta paywalls/captchas/DRM y guarda enlaces/embeds
de video de terceros (no descarga videos protegidos).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Permitir ejecutar como script desde la raíz del proyecto
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.utils import load_yaml, setup_logging, get_logger
from src.models import Run, Article
from src.database import Database
from src.source_loader import load_sources
from src.scraper import Scraper
from src.translator import Translator
from src.ranker import Ranker
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


def ask_inputs(args: argparse.Namespace, settings: dict) -> tuple[str, int, str]:
    d = settings.get("defaults", {})
    def_topic = d.get("topic", "tecnología, inteligencia artificial y avances tecnológicos")
    def_num = int(d.get("num_news", 5))
    def_lang = d.get("language", "es")

    if args.no_input:
        return (args.topic or def_topic, args.num or def_num, args.lang or def_lang)

    # Tema
    if args.topic:
        topic = args.topic
    else:
        try:
            entered = input(
                "¿Qué tema quieres buscar? Presiona ENTER para usar "
                "tecnología e inteligencia artificial por defecto: "
            ).strip()
        except EOFError:
            entered = ""
        topic = entered or def_topic

    # Número
    if args.num:
        num = args.num
    else:
        try:
            raw = input(f"¿Cuántas noticias quieres? (ENTER = {def_num}): ").strip()
        except EOFError:
            raw = ""
        num = int(raw) if raw.isdigit() and int(raw) > 0 else def_num

    # Idioma
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
def run() -> int:
    args = parse_args()
    settings = load_yaml(SETTINGS_PATH)
    log = setup_logging(settings.get("logging", {}).get("level", "INFO"))

    topic, num_target, lang = ask_inputs(args, settings)
    log.info(f"[bold cyan]Tema:[/] {topic}  |  [bold]Noticias:[/] {num_target}  |  "
             f"[bold]Idioma:[/] {lang}")

    # Componentes
    db = Database(settings.get("database", {}).get("path", "data/news.db"))
    sources = load_sources(SOURCES_PATH, only_enabled=True)
    for s in sources:
        db.upsert_source(s.name, s.trusted, s.region, s.enabled)

    scraper = Scraper(settings)
    translator = Translator(settings)
    ranker = Ranker(settings)
    exporter = Exporter(settings)

    require_video = settings.get("video", {}).get("require_video", True)

    run_obj = Run(topic=topic, language=lang, requested=num_target,
                  output_dir=None)
    run_id = db.start_run(run_obj)

    # Contadores
    found = 0
    discarded_no_video = 0
    skipped_duplicates = 0

    candidates: list[Article] = []
    seen_in_run: set[str] = set()

    # ---------------------- Recolección ---------------------- #
    # Se sobre-recolecta (3x) para luego elegir las mejores por ranking.
    target_pool = max(num_target * 3, num_target + 4)

    for source in sources:
        if len(candidates) >= target_pool:
            break
        log.info(f"[bold]Fuente:[/] {source.name}")
        try:
            urls = scraper.collect_article_urls(source)
        except Exception as exc:
            log.warning(f"  No se pudieron listar artículos de {source.name}: {exc}")
            continue
        log.info(f"  {len(urls)} enlaces candidatos")

        for url in urls:
            if len(candidates) >= target_pool:
                break
            try:
                article = scraper.fetch_article(url, source, topic)
            except Exception as exc:
                log.debug(f"  Error procesando {url}: {exc}")
                continue
            if article is None:
                continue

            # Sin video → descartar (si require_video)
            if require_video and not (article.video_url or article.video_embed_url):
                discarded_no_video += 1
                continue

            # Dedup en BD
            if db.is_duplicate(article):
                skipped_duplicates += 1
                log.debug(f"  Repetida (BD), se salta: {article.title_original[:60]}")
                continue
            # Dedup dentro de esta misma ejecución
            key = article.canonical_url or article.article_url
            if key in seen_in_run:
                skipped_duplicates += 1
                continue
            seen_in_run.add(key)

            # Puntuación
            ranker.score(
                article,
                trusted=source.trusted,
                is_duplicate=False,
                published_dt=getattr(article, "_published_dt", None),
            )
            if not ranker.passes(article):
                log.debug(f"  Puntuación baja ({article.score}): {article.title_original[:50]}")
                continue

            candidates.append(article)
            log.info(f"  [green]✓[/] candidata (score {article.score}): "
                     f"{article.title_original[:70]}")

    scraper.close()

    # ---------------------- Selección ---------------------- #
    best = Ranker.sort_best(candidates)[:num_target]

    # ---------------------- Traducción + export ---------------------- #
    run_dir = exporter.make_run_dir()
    final: list[Article] = []

    for i, article in enumerate(best, start=1):
        # Traducir título y resumen al idioma destino
        src_lang = article.language_original
        article.title_es = translator.translate(article.title_original, src_lang) \
            if lang.startswith("es") else article.title_original
        article.summary_es = translator.translate(article.summary_original, src_lang) \
            if lang.startswith("es") else article.summary_original
        article.carousel_text = exporter._build_carousel_text(article)

        article.run_id = run_id
        article.status = "selected"

        # Guardar en BD
        try:
            db.insert_article(article)
        except Exception as exc:
            log.warning(f"No se pudo guardar en BD: {exc}")

        # Exportar carpeta
        folder = exporter.export_article(run_dir, i, article)
        article.status = "exported"
        final.append(article)
        log.info(f"[green]Exportada[/] noticia_{i:02d} -> {folder}")

    found = len(final)
    db.finish_run(run_id, found, discarded_no_video, skipped_duplicates, str(run_dir))
    db.close()

    # ---------------------- Resumen ---------------------- #
    print_summary(topic, run_dir, found, num_target, discarded_no_video,
                  skipped_duplicates, final, log)
    return 0


# --------------------------------------------------------------------------- #
def print_summary(topic, run_dir, found, target, discarded_no_video,
                  skipped_duplicates, final, log) -> None:
    log.info("")
    log.info("[bold green]==================== RESUMEN ====================[/]")
    log.info(f"Carpeta creada:               {run_dir}")
    log.info(f"Noticias generadas:           {found} / {target}")
    log.info(f"Descartadas por no tener video: {discarded_no_video}")
    log.info(f"Repetidas saltadas:           {skipped_duplicates}")
    if found < target:
        log.info(f"[yellow]Faltaron {target - found} noticias "
                 f"(se agotaron las fuentes/candidatas).[/]")

    if _console and final:
        table = Table(title="Noticias finales", show_lines=False)
        table.add_column("#", justify="right", style="cyan")
        table.add_column("Título (ES)", style="white", overflow="fold")
        table.add_column("Fuente", style="green")
        table.add_column("Score", justify="right")
        table.add_column("Video", style="magenta")
        for i, a in enumerate(final, start=1):
            table.add_row(str(i), (a.title_es or a.title_original)[:70],
                          a.source_name, str(a.score), a.video_type or "-")
        _console.print(table)
    else:
        for i, a in enumerate(final, start=1):
            log.info(f"  {i:02d}. {a.title_es or a.title_original[:70]} "
                     f"[{a.source_name}] score={a.score}")

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
