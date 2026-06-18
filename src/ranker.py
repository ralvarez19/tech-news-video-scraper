"""ranker.py — puntuación estricta para elegir las mejores noticias Tech/IA.

IMPORTANTE: ninguna noticia puede llegar al top si no pasó el filtro temático
(`is_valid_tech_ai_news`). Eso se marca con `article._topic_valid` y se respeta
en `passes()`. El filtro se aplica en app.py ANTES del ranking.

Puntos (configurables en settings.yaml -> ranking.weights):
  +5 IA / ML / modelos / robots / chips
  +4 tecnología futurista
  +3 video o imagen usable
  +3 video claro
  +3 fuente tecnológica confiable
  +2 reciente
  +2 impacto global
  +2 dispositivos / avances visuales
  -10 política general
  -8  economía general sin tecnología
  -10 crimen / farándula / deportes
  -5  título ambiguo sin tema tech
  -10 repetida
"""
from __future__ import annotations

import re

from .models import Article
from .utils import age_in_days, get_logger

log = get_logger()


_AI_KEYWORDS = [
    r"\bia\b", "inteligencia artificial", "artificial intelligence",
    "machine learning", "aprendizaje autom", "deep learning", "redes neuronales",
    "neural network", "modelo de lenguaje", "language model", r"\bllm\b",
    "chatgpt", "openai", "anthropic", "claude", "gemini", "deepmind",
    "chip", "semiconductor", "gpu", "nvidia", "algoritmo", "algorithm",
]

_FUTURISTIC_KEYWORDS = [
    "cuántic", "quantum", "humanoid", "humanoide", "agi",
    "autónom", "autonomous", "exoesqueleto", "holograma", "metaverso",
    "biotec", "nanotec", "fusion nuclear", "neuralink", "brain-computer",
    "interfaz cerebro", "drone", "dron", "satélite", "space", "espacial",
]

_VISUAL_DEVICE_KEYWORDS = [
    "robot", "device", "dispositivo", "gadget", "wearable", "smartphone",
    "gafas", "glasses", "headset", "realidad virtual", "realidad aumentada",
    r"\bvr\b", r"\bar\b", "prototip", "unveil", "presenta", "lanza", "muestra",
    "demo", "prototype",
]

_GLOBAL_KEYWORDS = [
    "global", "world", "mundial", "international", "internacional", "europe",
    "europa", "china", "estados unidos", "united states", "worldwide",
    "billion", "millones de usuarios",
]

# Penalizaciones temáticas (refuerzan al filtro; suelen descartarse antes)
_POLITICAL = ["elecciones", "presidente", "gobierno", "congreso",
              "partido polít", "campaña electoral", "escándalo polít"]
_ECONOMY = ["bolsa de valores", "inflación", "mercados bursátiles",
            "acciones de la bolsa", "pib", "tipos de interés"]
_TABLOID = ["crimen", "asesinato", "fútbol", "deporte", "farándula",
            "celebridad", "religión", "guerra", "conflicto armado"]

_TECH_ANY = _AI_KEYWORDS + _FUTURISTIC_KEYWORDS + _VISUAL_DEVICE_KEYWORDS + [
    "tecnología", "tech", "software", "hardware", "ciberseguridad",
    "cybersecurity", "startup", "innovación", "app", "data center",
]


def _has(text: str, patterns: list[str]) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(re.search(p, low) for p in patterns)


def _count(text: str, patterns: list[str]) -> int:
    if not text:
        return 0
    low = text.lower()
    return sum(1 for p in patterns if re.search(p, low))


class Ranker:
    def __init__(self, settings: dict):
        rk = (settings or {}).get("ranking", {})
        self.min_score = rk.get("min_score", 1)
        w = rk.get("weights", {}) or {}
        self.w = {
            "keyword_ai": w.get("keyword_ai", 5),
            "futuristic_tech": w.get("futuristic_tech", 4),
            "has_usable_media": w.get("has_usable_media", 3),
            "has_clear_video": w.get("has_clear_video", 3),
            "trusted_source": w.get("trusted_source", 3),
            "recent": w.get("recent", 2),
            "global_impact": w.get("global_impact", 2),
            "visual_devices": w.get("visual_devices", 2),
            "political": w.get("political", -10),
            "economy_no_tech": w.get("economy_no_tech", -8),
            "tabloid_sports_crime": w.get("tabloid_sports_crime", -10),
            "ambiguous_no_tech": w.get("ambiguous_no_tech", -5),
            "repeated": w.get("repeated", -10),
        }
        self.max_age_recent_days = 7

    def score(self, article: Article, *, trusted: bool, is_duplicate: bool,
              published_dt=None) -> Article:
        breakdown: dict[str, int] = {}
        text = " ".join(filter(None, [
            article.title_original, article.title_es,
            article.summary_original, article.summary_es,
        ]))

        # + IA
        if _has(text, _AI_KEYWORDS):
            breakdown["keyword_ai"] = self.w["keyword_ai"]
        # + tecnología futurista
        if _has(text, _FUTURISTIC_KEYWORDS):
            breakdown["futuristic_tech"] = self.w["futuristic_tech"]
        # + dispositivos / avances visuales
        if _has(text, _VISUAL_DEVICE_KEYWORDS):
            breakdown["visual_devices"] = self.w["visual_devices"]

        # + media usable
        if article.media_type in ("video", "image") or article.hero_image_url:
            breakdown["has_usable_media"] = self.w["has_usable_media"]
        # + video claro
        if article.video_url or article.video_embed_url:
            if article.video_type in ("youtube", "vimeo", "dailymotion",
                                      "html5", "jsonld", "og_video"):
                breakdown["has_clear_video"] = self.w["has_clear_video"]
            else:
                breakdown["has_clear_video"] = max(1, self.w["has_clear_video"] // 2)

        # + fuente confiable
        if trusted:
            breakdown["trusted_source"] = self.w["trusted_source"]
        # + reciente
        age = age_in_days(published_dt)
        if age is not None and age <= self.max_age_recent_days:
            breakdown["recent"] = self.w["recent"]
        elif age is not None and age <= 21:
            breakdown["recent"] = max(1, self.w["recent"] // 2)
        # + impacto global
        if _has(text, _GLOBAL_KEYWORDS):
            breakdown["global_impact"] = self.w["global_impact"]

        # - penalizaciones temáticas
        if _has(text, _POLITICAL):
            breakdown["political"] = self.w["political"]
        if _has(text, _ECONOMY) and not _has(text, _TECH_ANY):
            breakdown["economy_no_tech"] = self.w["economy_no_tech"]
        if _has(text, _TABLOID):
            breakdown["tabloid_sports_crime"] = self.w["tabloid_sports_crime"]
        if not _has(text, _TECH_ANY):
            breakdown["ambiguous_no_tech"] = self.w["ambiguous_no_tech"]

        # - repetida
        if is_duplicate:
            breakdown["repeated"] = self.w["repeated"]

        article.score = sum(breakdown.values())
        article.score_breakdown = breakdown
        return article

    def passes(self, article: Article) -> bool:
        # GATE DURO: si no pasó el filtro temático, jamás entra al top.
        if getattr(article, "_topic_valid", True) is False:
            return False
        return article.score >= self.min_score

    @staticmethod
    def sort_best(articles: list[Article]) -> list[Article]:
        # Seguridad extra: excluir cualquiera marcado como no válido temáticamente.
        valid = [a for a in articles if getattr(a, "_topic_valid", True) is not False]
        return sorted(valid, key=lambda a: a.score, reverse=True)
