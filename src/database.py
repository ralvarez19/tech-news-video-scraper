"""database.py — capa SQLite.

Crea el esquema (runs, sources, articles), guarda noticias y proporciona
funciones de deduplicación:
  - por canonical_url
  - por article_url
  - por hash de título normalizado (content_hash incluye el título)

Diseñada para reutilizarse desde una API (FastAPI) más adelante.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .models import Article, Run
from .utils import get_logger, now_utc, iso, title_hash

log = get_logger()


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT UNIQUE NOT NULL,
    trusted       INTEGER DEFAULT 0,
    region        TEXT,
    enabled       INTEGER DEFAULT 1,
    last_seen_at  TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    topic                TEXT,
    language             TEXT,
    requested            INTEGER,
    started_at           TEXT,
    finished_at          TEXT,
    found                INTEGER DEFAULT 0,
    discarded_no_video   INTEGER DEFAULT 0,
    skipped_duplicates   INTEGER DEFAULT 0,
    output_dir           TEXT
);

CREATE TABLE IF NOT EXISTS articles (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER,
    topic             TEXT,
    title_original    TEXT,
    title_es          TEXT,
    summary_original  TEXT,
    summary_es        TEXT,
    language_original TEXT,
    source_name       TEXT,
    source_url        TEXT,
    article_url       TEXT,
    canonical_url     TEXT,
    video_url         TEXT,
    video_embed_url   TEXT,
    video_type        TEXT,
    published_at      TEXT,
    scraped_at        TEXT,
    content_hash      TEXT,
    title_hash        TEXT,
    status            TEXT,
    output_folder     TEXT,
    FOREIGN KEY (run_id) REFERENCES runs (id)
);

CREATE INDEX IF NOT EXISTS idx_articles_canonical ON articles (canonical_url);
CREATE INDEX IF NOT EXISTS idx_articles_articleurl ON articles (article_url);
CREATE INDEX IF NOT EXISTS idx_articles_titlehash  ON articles (title_hash);
CREATE INDEX IF NOT EXISTS idx_articles_contenthash ON articles (content_hash);
"""


class Database:
    def __init__(self, path: str = "data/news.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self._create_schema()

    # ------------------------------------------------------------------ #
    def _create_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    # ---------------------------- sources ----------------------------- #
    def upsert_source(self, name: str, trusted: bool, region: str, enabled: bool) -> None:
        self.conn.execute(
            """
            INSERT INTO sources (name, trusted, region, enabled, last_seen_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                trusted=excluded.trusted,
                region=excluded.region,
                enabled=excluded.enabled,
                last_seen_at=excluded.last_seen_at
            """,
            (name, int(trusted), region, int(enabled), iso(now_utc())),
        )
        self.conn.commit()

    # ------------------------------ runs ------------------------------ #
    def start_run(self, run: Run) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO runs (topic, language, requested, started_at, output_dir)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run.topic, run.language, run.requested, iso(now_utc()), run.output_dir),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, found: int, discarded_no_video: int,
                   skipped_duplicates: int, output_dir: Optional[str]) -> None:
        self.conn.execute(
            """
            UPDATE runs SET finished_at=?, found=?, discarded_no_video=?,
                            skipped_duplicates=?, output_dir=?
            WHERE id=?
            """,
            (iso(now_utc()), found, discarded_no_video, skipped_duplicates,
             output_dir, run_id),
        )
        self.conn.commit()

    # ---------------------------- dedup ------------------------------- #
    def is_duplicate(self, article: Article) -> bool:
        """True si la noticia ya existe por canonical_url, article_url o título."""
        th = title_hash(article.title_original or article.title_es)
        cur = self.conn.execute(
            """
            SELECT 1 FROM articles
            WHERE (canonical_url IS NOT NULL AND canonical_url != '' AND canonical_url = ?)
               OR (article_url   IS NOT NULL AND article_url   != '' AND article_url   = ?)
               OR (title_hash    IS NOT NULL AND title_hash    != '' AND title_hash    = ?)
            LIMIT 1
            """,
            (article.canonical_url, article.article_url, th),
        )
        return cur.fetchone() is not None

    # ---------------------------- insert ------------------------------ #
    def insert_article(self, article: Article) -> int:
        row = article.to_db_row()
        row["title_hash"] = title_hash(article.title_original or article.title_es)
        cols = list(row.keys())
        placeholders = ", ".join("?" for _ in cols)
        sql = f"INSERT INTO articles ({', '.join(cols)}) VALUES ({placeholders})"
        cur = self.conn.execute(sql, [row[c] for c in cols])
        self.conn.commit()
        return int(cur.lastrowid)

    def update_article_output(self, article_id: int, folder: str, status: str) -> None:
        self.conn.execute(
            "UPDATE articles SET output_folder=?, status=? WHERE id=?",
            (folder, status, article_id),
        )
        self.conn.commit()

    # ---------------------------- queries ----------------------------- #
    def count_articles(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0])
