"""video_detector.py — detección de video dentro del HTML de una noticia.

Estrategias (en orden de fiabilidad):
  1. JSON-LD VideoObject (schema.org)
  2. Open Graph de video (og:video, og:video:url, twitter:player)
  3. <video> nativo (HTML5) con <source>
  4. <iframe> de reproductores (YouTube, Vimeo, Dailymotion, JW, etc.)
  5. Enlaces <a> claramente asociados a un video

Devuelve un VideoInfo. NO descarga el video: solo extrae enlaces/embeds
públicos, respetando copyright y DRM.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from bs4 import BeautifulSoup

from .models import VideoInfo
from .utils import absolutize, get_logger

log = get_logger()


# Dominios de reproductores conocidos -> tipo
_PLAYER_PATTERNS = {
    "youtube": [r"youtube\.com/embed/", r"youtube\.com/watch", r"youtu\.be/",
                r"youtube-nocookie\.com/embed/"],
    "vimeo": [r"player\.vimeo\.com/video/", r"vimeo\.com/\d+"],
    "dailymotion": [r"dailymotion\.com/embed/", r"dai\.ly/", r"dailymotion\.com/video/"],
    "jwplayer": [r"cdn\.jwplayer\.com/", r"content\.jwplatform\.com/"],
    "brightcove": [r"players\.brightcove\.net/"],
    "twitch": [r"player\.twitch\.tv/"],
    "facebook": [r"facebook\.com/plugins/video", r"fb\.watch/"],
}

# Embeds que en realidad son publicidad / redes / no-video → ignorar
_IGNORE_IFRAME = [
    r"doubleclick", r"googlesyndication", r"adservice", r"taboola",
    r"outbrain", r"disqus", r"/ads/", r"newsletter", r"consent", r"captcha",
]


def _match_player(url: str) -> Optional[str]:
    low = url.lower()
    for vtype, patterns in _PLAYER_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, low):
                return vtype
    return None


def _youtube_embed(url: str) -> str:
    """Normaliza una URL de YouTube a su forma /embed/."""
    m = re.search(r"(?:v=|youtu\.be/|embed/)([A-Za-z0-9_\-]{6,})", url)
    if m:
        return f"https://www.youtube.com/embed/{m.group(1)}"
    return url


def _vimeo_embed(url: str) -> str:
    m = re.search(r"vimeo\.com/(?:video/)?(\d+)", url)
    if m:
        return f"https://player.vimeo.com/video/{m.group(1)}"
    return url


def _normalize_embed(vtype: str, url: str) -> str:
    if vtype == "youtube":
        return _youtube_embed(url)
    if vtype == "vimeo":
        return _vimeo_embed(url)
    return url


# --------------------------------------------------------------------------- #
def _from_jsonld(soup: BeautifulSoup, base_url: str) -> Optional[VideoInfo]:
    for tag in soup.find_all("script", type="application/ld+json"):
        if not tag.string:
            continue
        try:
            data = json.loads(tag.string)
        except Exception:
            # algunos sitios meten varios objetos JSON o JSON inválido
            try:
                data = json.loads(re.sub(r",\s*}", "}", tag.string))
            except Exception:
                continue
        for obj in _iter_jsonld_objects(data):
            t = obj.get("@type", "")
            types = t if isinstance(t, list) else [t]
            if any("VideoObject" in str(x) for x in types):
                content = (obj.get("contentUrl") or obj.get("embedUrl")
                           or obj.get("url") or "")
                embed = obj.get("embedUrl") or content
                if content or embed:
                    vtype = _match_player(content or embed) or "jsonld"
                    return VideoInfo(
                        found=True,
                        video_type=vtype,
                        video_url=absolutize(base_url, content or embed),
                        video_embed_url=_normalize_embed(
                            vtype, absolutize(base_url, embed or content)),
                        related=True,
                    )
    return None


def _iter_jsonld_objects(data):
    if isinstance(data, dict):
        if "@graph" in data and isinstance(data["@graph"], list):
            for item in data["@graph"]:
                yield from _iter_jsonld_objects(item)
        yield data
    elif isinstance(data, list):
        for item in data:
            yield from _iter_jsonld_objects(item)


def _from_opengraph(soup: BeautifulSoup, base_url: str) -> Optional[VideoInfo]:
    candidates = []
    for prop in ("og:video:url", "og:video:secure_url", "og:video", "twitter:player"):
        for tag in soup.find_all("meta", attrs={"property": prop}):
            if tag.get("content"):
                candidates.append(tag["content"])
        for tag in soup.find_all("meta", attrs={"name": prop}):
            if tag.get("content"):
                candidates.append(tag["content"])

    for url in candidates:
        if not url:
            continue
        abs_url = absolutize(base_url, url)
        vtype = _match_player(abs_url) or "og_video"
        return VideoInfo(
            found=True,
            video_type=vtype,
            video_url=abs_url,
            video_embed_url=_normalize_embed(vtype, abs_url),
            related=True,
        )
    return None


def _from_html5_video(soup: BeautifulSoup, base_url: str) -> Optional[VideoInfo]:
    for video in soup.find_all("video"):
        src = video.get("src")
        if not src:
            source = video.find("source")
            if source and source.get("src"):
                src = source["src"]
        if src:
            abs_url = absolutize(base_url, src)
            return VideoInfo(
                found=True,
                video_type="html5",
                video_url=abs_url,
                video_embed_url=abs_url,
                related=True,
            )
    return None


def _from_iframes(soup: BeautifulSoup, base_url: str) -> Optional[VideoInfo]:
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src") or ""
        if not src:
            continue
        low = src.lower()
        if any(re.search(p, low) for p in _IGNORE_IFRAME):
            continue
        vtype = _match_player(src)
        if vtype:
            abs_url = absolutize(base_url, src)
            return VideoInfo(
                found=True,
                video_type=vtype,
                video_url=abs_url,
                video_embed_url=_normalize_embed(vtype, abs_url),
                related=True,
            )
    return None


def _from_links(soup: BeautifulSoup, base_url: str) -> Optional[VideoInfo]:
    for a in soup.find_all("a", href=True):
        href = a["href"]
        vtype = _match_player(href)
        if vtype:
            abs_url = absolutize(base_url, href)
            # Heurística de relación: enlaces dentro del artículo se consideran
            # relacionados; aun así marcamos related=True por defecto.
            return VideoInfo(
                found=True,
                video_type=vtype,
                video_url=abs_url,
                video_embed_url=_normalize_embed(vtype, abs_url),
                related=True,
            )
    return None


# --------------------------------------------------------------------------- #
def detect_video(html: str, base_url: str, accept_types: list[str] | None = None) -> VideoInfo:
    """Analiza el HTML de un artículo y devuelve VideoInfo.

    accept_types: lista de tipos aceptados (de settings.yaml). Si un video
    detectado no está en la lista, se considera no encontrado.
    """
    if not html:
        return VideoInfo(found=False)

    soup = BeautifulSoup(html, "html.parser")

    for strategy in (_from_jsonld, _from_opengraph, _from_html5_video,
                     _from_iframes, _from_links):
        try:
            info = strategy(soup, base_url)
        except Exception as exc:  # nunca dejar que un sitio raro rompa todo
            log.debug(f"Estrategia {strategy.__name__} falló: {exc}")
            info = None
        if info and info.found:
            if accept_types and info.video_type not in accept_types:
                # tipo detectado no aceptado; seguimos probando otras estrategias
                continue
            return info

    return VideoInfo(found=False)
