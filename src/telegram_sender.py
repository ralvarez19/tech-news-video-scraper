"""telegram_sender.py — envía los slides generados a Telegram.

Controlado por variables de entorno (.env):
    TELEGRAM_ENABLED        true/false
    TELEGRAM_BOT_TOKEN      token del bot
    TELEGRAM_CHAT_ID        chat/canal destino
    TELEGRAM_SEND_AS_ALBUM  true/false (álbum con sendMediaGroup)

Comportamiento robusto:
  - Si faltan variables → "[TELEGRAM] No configurado. Se omite envío."
  - Si está desactivado → "[TELEGRAM] Desactivado por TELEGRAM_ENABLED=false"
  - Álbum vía sendMediaGroup; si falla, fallback a sendPhoto uno por uno.
  - Nunca lanza excepción que detenga el programa.
"""
from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any, Optional

import requests

from .utils import get_logger

log = get_logger()

API = "https://api.telegram.org/bot{token}/{method}"
CAPTION_LIMIT = 1024


def _truthy(val: Optional[str]) -> bool:
    return str(val).strip().lower() in ("1", "true", "yes", "on", "si", "sí")


def _get(article: Any, key: str, default=""):
    if isinstance(article, dict):
        return article.get(key, default)
    return getattr(article, key, default)


def _slide_path(run_output_dir: Path, index: int, article: Any) -> Optional[Path]:
    # 1) ruta guardada en el artículo
    p = _get(article, "local_slide_path", "")
    if p and Path(p).exists():
        return Path(p)
    # 2) ruta estándar noticia_XX/slide.png
    cand = run_output_dir / f"noticia_{index:02d}" / "slide.png"
    return cand if cand.exists() else None


def _caption(index: int, article: Any) -> str:
    title = _get(article, "short_headline_es") or _get(article, "title_es") \
        or _get(article, "title_original") or "Sin título"
    source = _get(article, "source_name", "")
    url = _get(article, "article_url", "")
    parts = [f"<b>#{index} · {html.escape(str(title))}</b>"]
    if source:
        parts.append(f"📰 {html.escape(str(source))}")
    if url:
        parts.append(f'🔗 <a href="{html.escape(str(url))}">Ver artículo</a>')
    cap = "\n".join(parts)
    return cap[:CAPTION_LIMIT]


# --------------------------------------------------------------------------- #
def send_run_to_telegram(run_output_dir, articles: list) -> str:
    """Envía los slides del run a Telegram. Devuelve un estado legible.

    Estados: "sent" | "partial" | "not_configured" | "disabled" | "no_slides" | "error"
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass  # si no está python-dotenv, se usan las variables del entorno tal cual

    enabled_raw = os.getenv("TELEGRAM_ENABLED")
    if enabled_raw is not None and not _truthy(enabled_raw):
        log.info("[TELEGRAM] Desactivado por TELEGRAM_ENABLED=false")
        return "disabled"

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id or token.startswith("pon_aqui") or chat_id.startswith("pon_aqui"):
        log.info("[TELEGRAM] No configurado. Se omite envío.")
        return "not_configured"

    as_album = _truthy(os.getenv("TELEGRAM_SEND_AS_ALBUM", "true"))
    run_output_dir = Path(run_output_dir)

    # Recolectar slides + captions
    items: list[tuple[Path, str]] = []
    for i, article in enumerate(articles, start=1):
        sp = _slide_path(run_output_dir, i, article)
        if sp:
            items.append((sp, _caption(i, article)))

    if not items:
        log.info("[TELEGRAM] No hay slides para enviar.")
        return "no_slides"

    ok = False
    if as_album and len(items) > 1:
        ok = _send_album(token, chat_id, items)
        if not ok:
            log.info("[TELEGRAM] Álbum falló; se envían uno por uno.")
    if not ok:
        ok = _send_individually(token, chat_id, items)

    if ok:
        log.info("[TELEGRAM] Slides enviados correctamente.")
        return "sent"
    log.warning("[TELEGRAM] No se pudieron enviar los slides.")
    return "error"


# --------------------------------------------------------------------------- #
def _send_album(token: str, chat_id: str, items: list[tuple[Path, str]]) -> bool:
    """Envía hasta 10 fotos por álbum (sendMediaGroup)."""
    try:
        all_ok = True
        # Telegram limita a 10 medios por grupo
        for batch_start in range(0, len(items), 10):
            batch = items[batch_start:batch_start + 10]
            media = []
            files = {}
            handles = []
            for j, (path, cap) in enumerate(batch):
                key = f"photo{j}"
                fh = open(path, "rb")
                handles.append(fh)
                files[key] = fh
                media.append({"type": "photo", "media": f"attach://{key}",
                              "caption": cap, "parse_mode": "HTML"})
            try:
                resp = requests.post(
                    API.format(token=token, method="sendMediaGroup"),
                    data={"chat_id": chat_id, "media": json.dumps(media)},
                    files=files, timeout=60,
                )
            finally:
                for fh in handles:
                    try:
                        fh.close()
                    except Exception:
                        pass
            if not (resp.ok and resp.json().get("ok")):
                log.debug(f"sendMediaGroup respuesta: {resp.status_code} {resp.text[:200]}")
                all_ok = False
        return all_ok
    except Exception as exc:
        log.debug(f"Excepción en sendMediaGroup: {exc}")
        return False


def _send_individually(token: str, chat_id: str, items: list[tuple[Path, str]]) -> bool:
    """Fallback: una foto por mensaje (sendPhoto)."""
    sent = 0
    for path, cap in items:
        try:
            with open(path, "rb") as fh:
                resp = requests.post(
                    API.format(token=token, method="sendPhoto"),
                    data={"chat_id": chat_id, "caption": cap, "parse_mode": "HTML"},
                    files={"photo": fh}, timeout=60,
                )
            if resp.ok and resp.json().get("ok"):
                sent += 1
            else:
                log.debug(f"sendPhoto respuesta: {resp.status_code} {resp.text[:200]}")
        except Exception as exc:
            log.debug(f"Excepción en sendPhoto: {exc}")
    return sent > 0
