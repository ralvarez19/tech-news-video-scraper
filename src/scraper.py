"""scraper.py — descarga de listados y artículos.

Flujo por fuente:
  1. Si la fuente tiene RSS, se leen los enlaces del feed (preferido: estable y
     respetuoso).
  2. Si no, se descarga cada listing_url y se extraen enlaces de artículos que
     coincidan con article_pattern.
  3. Cada artículo se descarga (requests; Playwright solo si needs_js o si
     requests no encuentra video), se extraen metadatos y se busca video.

Principios de respeto:
  - Se consulta robots.txt (si respect_robots_txt=true) y se omiten URLs no
    permitidas.
  - No se intenta saltar paywalls, captchas, logins ni DRM.
  - Hay pausas entre peticiones (delay_between_requests).
  - Cualquier fallo de una fuente/artículo NO detiene el proceso global.
"""
from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from .models import Article, Source, VideoInfo
from .video_detector import detect_video
from .translator import detect_language
from .utils import (absolutize, canonical_url, get_logger, iso, now_utc,
                    parse_date, age_in_days)

log = get_logger()


class Scraper:
    def __init__(self, settings: dict):
        s = (settings or {}).get("search", {})
        self.timeout = s.get("request_timeout", 20)
        self.retries = s.get("retries", 2)
        self.delay = s.get("delay_between_requests", 1.0)
        self.max_per_source = s.get("max_articles_per_source", 25)
        self.max_age_days = s.get("max_age_days", 21)
        self.respect_robots = s.get("respect_robots_txt", True)
        self.user_agent = s.get("user_agent",
                                "TechNewsVideoScraper/1.0 (+local research tool)")

        pw = (settings or {}).get("playwright", {})
        self.pw_enabled = pw.get("enabled", True)
        self.pw_headless = pw.get("headless", True)
        self.pw_nav_timeout = pw.get("nav_timeout", 25000)

        vid = (settings or {}).get("video", {})
        self.accept_types = vid.get("accept_types")

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept-Language": "es,en;q=0.8",
        })
        self._robots_cache: dict[str, Optional[RobotFileParser]] = {}
        self._playwright = None  # se inicia perezosamente

    # ================================================================== #
    # robots.txt
    # ================================================================== #
    def _robots_for(self, url: str) -> Optional[RobotFileParser]:
        if not self.respect_robots:
            return None
        netloc = urlparse(url).netloc
        if netloc in self._robots_cache:
            return self._robots_cache[netloc]
        rp = RobotFileParser()
        robots_url = f"{urlparse(url).scheme}://{netloc}/robots.txt"
        try:
            resp = self.session.get(robots_url, timeout=self.timeout)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                rp = None
        except Exception:
            rp = None
        self._robots_cache[netloc] = rp
        return rp

    def _allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self._robots_for(url)
        if rp is None:
            return True  # sin robots.txt accesible → asumimos permitido
        try:
            return rp.can_fetch(self.user_agent, url)
        except Exception:
            return True

    # ================================================================== #
    # HTTP
    # ================================================================== #
    def _get(self, url: str) -> Optional[str]:
        if not self._allowed(url):
            log.info(f"[yellow]robots.txt no permite:[/] {url}")
            return None
        for attempt in range(self.retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code == 200:
                    return resp.text
                if resp.status_code in (401, 403):
                    log.info(f"[yellow]Bloqueado ({resp.status_code}), se omite:[/] {url}")
                    return None
                if resp.status_code == 404:
                    return None
            except requests.RequestException as exc:
                log.debug(f"Intento {attempt+1} falló para {url}: {exc}")
            time.sleep(self.delay)
        return None

    def _get_rendered(self, url: str) -> Optional[str]:
        """Renderiza con Playwright (solo cuando hace falta JavaScript)."""
        if not self.pw_enabled:
            return None
        if not self._allowed(url):
            return None
        try:
            if self._playwright is None:
                from playwright.sync_api import sync_playwright
                self._pw_ctx = sync_playwright().start()
                self._browser = self._pw_ctx.chromium.launch(headless=self.pw_headless)
                self._playwright = True
            page = self._browser.new_page(user_agent=self.user_agent)
            page.goto(url, timeout=self.pw_nav_timeout, wait_until="domcontentloaded")
            try:
                page.wait_for_timeout(1500)
            except Exception:
                pass
            html = page.content()
            page.close()
            return html
        except Exception as exc:
            log.debug(f"Playwright falló para {url}: {exc}")
            return None

    def close(self) -> None:
        try:
            if self._playwright:
                self._browser.close()
                self._pw_ctx.stop()
        except Exception:
            pass

    # ================================================================== #
    # Listados
    # ================================================================== #
    def collect_article_urls(self, source: Source) -> list[str]:
        urls: list[str] = []
        # 1) RSS preferido
        if source.rss:
            urls.extend(self._urls_from_rss(source.rss))
        # 2) Listados HTML
        if len(urls) < self.max_per_source:
            for listing in source.listing_urls:
                urls.extend(self._urls_from_listing(listing, source))
                if len(urls) >= self.max_per_source:
                    break
        # dedup conservando orden
        seen, out = set(), []
        for u in urls:
            cu = canonical_url(u)
            if cu and cu not in seen:
                seen.add(cu)
                out.append(u)
        return out[: self.max_per_source]

    def _urls_from_rss(self, rss_url: str) -> list[str]:
        xml = self._get(rss_url)
        if not xml:
            return []
        out: list[str] = []
        try:
            root = ET.fromstring(xml.encode("utf-8", errors="ignore"))
        except Exception:
            return []
        # RSS 2.0: channel/item/link  |  Atom: entry/link[@href]
        for item in root.iter():
            tag = item.tag.lower()
            if tag.endswith("item") or tag.endswith("entry"):
                link = None
                for child in item:
                    ctag = child.tag.lower()
                    if ctag.endswith("link"):
                        link = child.get("href") or (child.text or "").strip()
                        if link:
                            break
                if link:
                    out.append(link)
        return out

    def _urls_from_listing(self, listing_url: str, source: Source) -> list[str]:
        html = self._get(listing_url)
        if not html and source.needs_js:
            html = self._get_rendered(listing_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        out: list[str] = []
        for a in soup.find_all("a", href=True):
            href = absolutize(listing_url, a["href"])
            if source.article_pattern and source.article_pattern not in href:
                continue
            if "#" in href and href.split("#")[0] == listing_url:
                continue
            out.append(href)
        return out

    # ================================================================== #
    # Artículo individual
    # ================================================================== #
    def fetch_article(self, url: str, source: Source, topic: str) -> Optional[Article]:
        """Descarga y procesa un artículo. Devuelve un Article candidato o None.

        None significa: sin contenido / bloqueado. (La ausencia de video se
        refleja en el Article con status 'no_video'.)
        """
        html = self._get(url)
        if not html and source.needs_js:
            html = self._get_rendered(url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        title = self._extract_title(soup)
        summary = self._extract_summary(soup)
        published = self._extract_date(soup)
        canon = self._extract_canonical(soup, url)

        if not title:
            return None

        # ¿demasiado vieja?
        if self.max_age_days and published is not None:
            age = age_in_days(published)
            if age is not None and age > self.max_age_days:
                log.debug(f"Descartada por antigüedad ({age:.0f}d): {title[:60]}")
                return None

        # Detección de video (requests). Si no hay y la fuente puede usar JS,
        # reintentamos con render para no perder videos cargados dinámicamente.
        video = detect_video(html, url, self.accept_types)
        if not video.found and self.pw_enabled and not source.needs_js:
            rendered = self._get_rendered(url)
            if rendered:
                video = detect_video(rendered, url, self.accept_types)

        lang = detect_language(f"{title}. {summary}")

        article = Article(
            topic=topic,
            title_original=title,
            summary_original=summary,
            language_original=lang,
            source_name=source.name,
            source_url=source.listing_urls[0] if source.listing_urls else (source.rss or ""),
            article_url=url,
            canonical_url=canon or canonical_url(url),
            video_url=video.video_url,
            video_embed_url=video.video_embed_url,
            video_type=video.video_type,
            region=source.region,
            published_at=iso(published),
            scraped_at=iso(now_utc()),
            status="candidate" if video.found else "no_video",
        )
        if not video.related:
            setattr(article, "_video_unrelated", True)
        # guardamos el datetime para el ranking sin re-parsear
        setattr(article, "_published_dt", published)
        return article

    # ----------------------- extractores ----------------------------- #
    @staticmethod
    def _meta(soup: BeautifulSoup, *keys: str) -> Optional[str]:
        for key in keys:
            tag = (soup.find("meta", attrs={"property": key})
                   or soup.find("meta", attrs={"name": key}))
            if tag and tag.get("content"):
                return tag["content"].strip()
        return None

    def _extract_title(self, soup: BeautifulSoup) -> str:
        return (self._meta(soup, "og:title", "twitter:title")
                or (soup.title.string.strip() if soup.title and soup.title.string else "")
                or (soup.find("h1").get_text(strip=True) if soup.find("h1") else ""))

    def _extract_summary(self, soup: BeautifulSoup) -> str:
        return (self._meta(soup, "og:description", "twitter:description", "description")
                or "")

    def _extract_date(self, soup: BeautifulSoup):
        raw = (self._meta(soup, "article:published_time", "og:article:published_time",
                          "datePublished", "publishdate", "date")
               )
        if not raw:
            t = soup.find("time")
            if t:
                raw = t.get("datetime") or t.get_text(strip=True)
        return parse_date(raw)

    @staticmethod
    def _extract_canonical(soup: BeautifulSoup, url: str) -> str:
        link = soup.find("link", attrs={"rel": "canonical"})
        if link and link.get("href"):
            return canonical_url(link["href"])
        return canonical_url(url)
