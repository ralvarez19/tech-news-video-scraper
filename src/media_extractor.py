"""media_extractor.py — extracción de imágenes/posters y chequeo de embed.

Responsabilidades:
  - extract_hero_image(): imagen principal del artículo (og:image, twitter:image,
    JSON-LD image, primera imagen grande del contenido).
  - extract_video_poster(): thumbnail del video (JSON-LD VideoObject.thumbnailUrl,
    og:image como respaldo).
  - check_embeddable(): determina si una URL de video se puede meter en un iframe,
    inspeccionando cabeceras X-Frame-Options y Content-Security-Policy
    (frame-ancestors). Los hosts conocidos (YouTube, Vimeo, Dailymotion) se
    consideran embebibles.
  - download_image(): descarga una imagen y la guarda como JPG (con Pillow si está
    disponible; si no, guarda el binario tal cual).

No descarga videos protegidos: solo imágenes/posters públicos y referencias.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from .utils import absolutize, get_logger

log = get_logger()

# Hosts cuyo /embed permite framing de forma fiable.
_EMBEDDABLE_HOSTS = ("youtube.com/embed", "youtube-nocookie.com/embed",
                     "player.vimeo.com", "dailymotion.com/embed",
                     "players.brightcove.net", "player.twitch.tv")


# --------------------------------------------------------------------------- #
# Imágenes
# --------------------------------------------------------------------------- #
def _meta_content(soup: BeautifulSoup, *keys: str) -> Optional[str]:
    for key in keys:
        tag = (soup.find("meta", attrs={"property": key})
               or soup.find("meta", attrs={"name": key}))
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def extract_hero_image(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """Devuelve la URL de la imagen principal del artículo, o None."""
    url = _meta_content(soup, "og:image", "og:image:url", "og:image:secure_url",
                        "twitter:image", "twitter:image:src")
    if url:
        return absolutize(base_url, url)

    # JSON-LD: image puede ser str, dict{url} o lista
    for tag in soup.find_all("script", type="application/ld+json"):
        if not tag.string:
            continue
        try:
            data = json.loads(tag.string)
        except Exception:
            continue
        found = _jsonld_image(data)
        if found:
            return absolutize(base_url, found)

    # Primera <img> razonablemente grande dentro de <article> o del cuerpo
    container = soup.find("article") or soup
    for img in container.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src or src.startswith("data:"):
            continue
        if re.search(r"(sprite|logo|icon|avatar|placeholder|1x1|pixel)", src, re.I):
            continue
        return absolutize(base_url, src)
    return None


def _jsonld_image(data) -> Optional[str]:
    if isinstance(data, dict):
        if "image" in data:
            img = data["image"]
            if isinstance(img, str):
                return img
            if isinstance(img, dict):
                return img.get("url")
            if isinstance(img, list) and img:
                first = img[0]
                return first.get("url") if isinstance(first, dict) else first
        for v in data.values():
            r = _jsonld_image(v)
            if r:
                return r
    elif isinstance(data, list):
        for item in data:
            r = _jsonld_image(item)
            if r:
                return r
    return None


def extract_video_poster(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    """Devuelve un poster/thumbnail del video (JSON-LD o og:image)."""
    for tag in soup.find_all("script", type="application/ld+json"):
        if not tag.string:
            continue
        try:
            data = json.loads(tag.string)
        except Exception:
            continue
        thumb = _jsonld_thumbnail(data)
        if thumb:
            return absolutize(base_url, thumb)
    # respaldo: og:image
    return extract_hero_image(soup, base_url)


def _jsonld_thumbnail(data) -> Optional[str]:
    if isinstance(data, dict):
        t = data.get("@type", "")
        types = t if isinstance(t, list) else [t]
        if any("VideoObject" in str(x) for x in types):
            thumb = data.get("thumbnailUrl") or data.get("thumbnail")
            if isinstance(thumb, list) and thumb:
                thumb = thumb[0]
            if isinstance(thumb, dict):
                thumb = thumb.get("url")
            if thumb:
                return thumb
        if "@graph" in data:
            r = _jsonld_thumbnail(data["@graph"])
            if r:
                return r
    elif isinstance(data, list):
        for item in data:
            r = _jsonld_thumbnail(item)
            if r:
                return r
    return None


def youtube_thumbnail(video_url: str) -> Optional[str]:
    """Construye la miniatura de YouTube a partir del ID."""
    m = re.search(r"(?:v=|youtu\.be/|embed/)([A-Za-z0-9_\-]{6,})", video_url or "")
    if m:
        return f"https://i.ytimg.com/vi/{m.group(1)}/hqdefault.jpg"
    return None


# --------------------------------------------------------------------------- #
# ¿Embebible?
# --------------------------------------------------------------------------- #
def check_embeddable(embed_url: str, session: Optional[requests.Session] = None,
                     timeout: int = 15) -> tuple[bool, str]:
    """Devuelve (embebible, motivo).

    motivo: "ok" | "x_frame_options:DENY" | "csp_frame_ancestors" |
            "host_known_embeddable" | "unreachable" | "no_url"
    """
    if not embed_url:
        return False, "no_url"

    low = embed_url.lower()
    if any(h in low for h in _EMBEDDABLE_HOSTS):
        return True, "host_known_embeddable"

    sess = session or requests
    try:
        resp = sess.get(embed_url, timeout=timeout, stream=True,
                        headers={"User-Agent": "Mozilla/5.0"})
        xfo = resp.headers.get("X-Frame-Options", "").upper()
        csp = resp.headers.get("Content-Security-Policy", "").lower()
        try:
            resp.close()
        except Exception:
            pass
        if "DENY" in xfo:
            return False, "x_frame_options:DENY"
        if "SAMEORIGIN" in xfo:
            return False, "x_frame_options:SAMEORIGIN"
        if "frame-ancestors" in csp:
            # si frame-ancestors no incluye 'self'/* abierto, lo tratamos como bloqueado
            m = re.search(r"frame-ancestors([^;]*)", csp)
            directive = m.group(1).strip() if m else ""
            if "*" not in directive:
                return False, "csp_frame_ancestors"
        return True, "ok"
    except requests.RequestException:
        # Si no podemos comprobarlo, somos conservadores: tratamos como bloqueado
        # para forzar el fallback a poster/imagen (más robusto visualmente).
        return False, "unreachable"


# --------------------------------------------------------------------------- #
# Descarga de imágenes
# --------------------------------------------------------------------------- #
def download_image(url: str, dest_path: str | Path,
                   session: Optional[requests.Session] = None,
                   timeout: int = 20, max_side: int = 1600) -> bool:
    """Descarga una imagen y la guarda como JPG en dest_path. True si éxito."""
    if not url:
        return False
    dest = Path(dest_path)
    sess = session or requests
    try:
        resp = sess.get(url, timeout=timeout,
                        headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200 or not resp.content:
            return False
        raw = resp.content
    except requests.RequestException as exc:
        log.debug(f"No se pudo descargar imagen {url}: {exc}")
        return False

    # Intentar normalizar con Pillow → JPG
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        img = img.convert("RGB")
        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)))
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, "JPEG", quality=88)
        return True
    except Exception as exc:
        log.debug(f"Pillow no pudo procesar imagen ({exc}); se guarda binario.")
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
            return True
        except Exception:
            return False
