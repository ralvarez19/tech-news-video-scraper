"""ranker.py — sistema de puntuación para elegir las mejores noticias.

Puntúa cada noticia según:
  +  menciona IA / ML / modelos / robots / chips / avances científicos
  +  es reciente
  +  tiene video claro
  +  es de fuente confiable
  +  tiene impacto global
  -  es repetida
  -  es publicidad disfrazada
  -  no tiene fecha clara
  -  el video no está directamente relacionado

Los pesos son configurables en settings.yaml -> ranking.weights.
Devuelve la noticia con .score y .score_breakdown rellenados.
"""
from __future__ import annotations

import re

from .models import Article
from .utils import age_in_days, get_logger

log = get_logger()


# Palabras clave de alto valor (IA / tecnología / ciencia aplicada)
_AI_KEYWORDS = [
    r"\bia\b", "inteligencia artificial", "artificial intelligence",
    "machine learning", "aprendizaje autom", "deep learning", "redes neuronales",
    "neural network", "modelo de lenguaje", "language model", r"\bllm\b",
    "chatgpt", "openai", "anthropic", "claude", "gemini", "deepmind",
    "robot", "robótica", "robotics", "chip", "semiconductor", "gpu", "nvidia",
    "cuántic", "quantum", "algoritmo", "algorithm", "automatiz", "automation",
    "biotec", "nanotec", "space", "espacial", "satélite", "fusion",
    "breakthrough", "avance", "innovación", "innovation", "research", "científic",
]

# Señales de impacto global
_GLOBAL_KEYWORDS = [
    "global", "world", "mundial", "international", "internacional", "europe",
    "europa", "china", "estados unidos", "united states", "eu ", "g7", "onu",
    "billion", "millones", "millones de usuarios", "worldwide",
]

# Señales de publicidad disfrazada / contenido promocional
_AD_SIGNALS = [
    "sponsored", "patrocinado", "publirreportaje", "advertorial", "promo code",
    "código de descuento", "discount code", "buy now", "compra ya", "oferta",
    "deal of the day", "affiliate", "review:", "unboxing", "% off", "descuento",
    "best deals", "shop now",
]


def _count_matches(text: str, patterns: list[str]) -> int:
    if not text:
        return 0
    low = text.lower()
    n = 0
    for p in patterns:
        if re.search(p, low):
            n += 1
    return n


class Ranker:
    def __init__(self, settings: dict):
        rk = (settings or {}).get("ranking", {})
        self.min_score = rk.get("min_score", 1)
        w = rk.get("weights", {}) or {}
        self.w = {
            "keyword_ai": w.get("keyword_ai", 5),
            "recent": w.get("recent", 4),
            "has_clear_video": w.get("has_clear_video", 4),
            "has_usable_media": w.get("has_usable_media", 2),
            "good_headline": w.get("good_headline", 2),
            "trusted_source": w.get("trusted_source", 3),
            "global_impact": w.get("global_impact", 3),
            "repeated": w.get("repeated", -10),
            "disguised_ad": w.get("disguised_ad", -6),
            "no_clear_date": w.get("no_clear_date", -3),
            "unrelated_video": w.get("unrelated_video", -4),
        }
        self.max_age_recent_days = 7  # "reciente" = última semana

    def score(self, article: Article, *, trusted: bool, is_duplicate: bool,
              published_dt=None) -> Article:
        breakdown: dict[str, int] = {}
        text = " ".join(filter(None, [
            article.title_original, article.title_es,
            article.summary_original, article.summary_es,
        ]))

        # + IA / tecnología (se escala suavemente según nº de coincidencias)
        ai_hits = _count_matches(text, _AI_KEYWORDS)
        if ai_hits:
            pts = min(self.w["keyword_ai"], 1 + ai_hits) if self.w["keyword_ai"] > 0 else 0
            pts = self.w["keyword_ai"] if ai_hits >= 2 else max(1, self.w["keyword_ai"] // 2)
            breakdown["keyword_ai"] = pts

        # + reciente
        age = age_in_days(published_dt)
        if age is not None:
            if age <= self.max_age_recent_days:
                breakdown["recent"] = self.w["recent"]
            elif age <= 21:
                breakdown["recent"] = max(1, self.w["recent"] // 2)
        else:
            breakdown["no_clear_date"] = self.w["no_clear_date"]

        # + video claro
        if article.video_url or article.video_embed_url:
            if article.video_type in ("youtube", "vimeo", "dailymotion",
                                      "html5", "jsonld", "og_video"):
                breakdown["has_clear_video"] = self.w["has_clear_video"]
            else:
                breakdown["has_clear_video"] = max(1, self.w["has_clear_video"] // 2)

        # + media usable (video o imagen sirven para el slide)
        if article.media_type in ("video", "image") or article.hero_image_url:
            breakdown["has_usable_media"] = self.w["has_usable_media"]

        # + buen titular (longitud adecuada, no vacío, no excesivamente largo)
        headline = article.title_original or article.title_es
        if headline:
            n = len(headline)
            if 25 <= n <= 120 and not headline.endswith("..."):
                breakdown["good_headline"] = self.w["good_headline"]

        # + fuente confiable
        if trusted:
            breakdown["trusted_source"] = self.w["trusted_source"]

        # + impacto global
        if _count_matches(text, _GLOBAL_KEYWORDS):
            breakdown["global_impact"] = self.w["global_impact"]

        # - repetida
        if is_duplicate:
            breakdown["repeated"] = self.w["repeated"]

        # - publicidad disfrazada
        if _count_matches(text, _AD_SIGNALS):
            breakdown["disguised_ad"] = self.w["disguised_ad"]

        # - video no relacionado
        # (related=False lo marca el detector; aquí lo reflejamos si viene en metadata)
        if getattr(article, "_video_unrelated", False):
            breakdown["unrelated_video"] = self.w["unrelated_video"]

        total = sum(breakdown.values())
        article.score = total
        article.score_breakdown = breakdown
        return article

    def passes(self, article: Article) -> bool:
        return article.score >= self.min_score

    @staticmethod
    def sort_best(articles: list[Article]) -> list[Article]:
        return sorted(articles, key=lambda a: a.score, reverse=True)
