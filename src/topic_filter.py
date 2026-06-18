"""topic_filter.py — filtro temático OBLIGATORIO de Tecnología / IA.

Se aplica ANTES del ranking y ANTES de guardar/exportar. Si una noticia no es
de tecnología/IA, no entra: no se guarda en SQLite ni se genera su slide.

Función principal:
    is_valid_tech_ai_news(article, config) -> (bool, reason, score)
        bool   : si la noticia es válida (tecnología/IA)
        reason : "accepted" | "not_tech" | "political_general"
        score  : puntaje temático

Reglas:
  1. Necesita al menos `min_topic_score` para aceptarse.
  2. Si hay palabras negativas fuertes y no hay núcleo tech/IA suficiente → rechazo.
  3. Si el título no tiene nada tech/IA, se revisa resumen + tags + metadata.
  4. Si aun así no se detecta tecnología/IA → rechazo.
  5. Se puede aceptar política/regulación SOLO si está ligada a IA/tecnología
     (porque entonces aparecen términos núcleo como "inteligencia artificial",
     "chip", "ciberseguridad", etc., y el score supera el umbral).

La política, economía general, crimen, deportes, farándula, etc., se descartan.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional

from .utils import get_logger

log = get_logger()


# --------------------------------------------------------------------------- #
# Listas por defecto (se pueden sobreescribir desde settings.yaml -> topic_filter)
# --------------------------------------------------------------------------- #
DEFAULT_POSITIVE = [
    "inteligencia artificial", "ia", "ai", "artificial intelligence",
    "machine learning", "deep learning", "modelo de ia", "modelos de ia",
    "language model", "llm", "chatbot", "robot", "robotica", "robotics",
    "tecnologia", "tech", "software", "hardware", "chip", "chips",
    "semiconductor", "nvidia", "openai", "google ai", "gemini", "anthropic",
    "claude", "microsoft", "apple intelligence", "samsung", "tesla", "spacex",
    "computacion cuantica", "quantum computing", "ciberseguridad",
    "cybersecurity", "realidad virtual", "realidad aumentada",
    "startup tecnologica", "automatizacion", "automation", "dispositivo inteligente",
    "wearable", "smartphone", "app", "data center", "gpu", "robot humanoide",
    "humanoide", "innovacion tecnologica", "algoritmo", "neural", "deepmind",
]

# Términos "núcleo": confirman tecnología/IA de forma fuerte (cuentan doble).
DEFAULT_CORE = [
    "inteligencia artificial", "artificial intelligence", "machine learning",
    "deep learning", "openai", "anthropic", "claude", "gemini", "chatgpt",
    "llm", "modelo de ia", "nvidia", "gpu", "chip", "chips", "semiconductor",
    "robot", "robotica", "robotics", "computacion cuantica", "quantum computing",
    "ciberseguridad", "cybersecurity", "ia", "ai", "humanoide", "deepmind",
]

DEFAULT_NEGATIVE = [
    "elecciones", "presidente", "gobierno", "congreso", "partido politico",
    "campana electoral", "crimen", "asesinato", "guerra", "conflicto armado",
    "deporte", "deportes", "futbol", "farandula", "celebridad", "religion",
    "escandalo politico", "bolsa de valores", "inflacion",
]

# Tokens cortos que requieren límite de palabra para evitar falsos positivos
# (p. ej. "ai" dentro de "aire", "app" dentro de "appliance").
SHORT_TOKENS = {"ia", "ai", "app", "gpu", "vr", "ar", "tech"}


# --------------------------------------------------------------------------- #
def _strip(text: str) -> str:
    """minúsculas + sin acentos (para comparar con keywords normalizadas)."""
    if not text:
        return ""
    txt = unicodedata.normalize("NFKD", text)
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return txt.lower()


def _matches(text_norm: str, kw_norm: str) -> bool:
    if not kw_norm:
        return False
    if kw_norm in SHORT_TOKENS or (len(kw_norm) <= 3 and " " not in kw_norm):
        return re.search(rf"(?<![\w]){re.escape(kw_norm)}(?![\w])", text_norm) is not None
    return kw_norm in text_norm


def _found(text_norm: str, keywords: list[str]) -> list[str]:
    out = []
    for kw in keywords:
        kwn = _strip(kw)
        if _matches(text_norm, kwn):
            out.append(kwn)
    return sorted(set(out))


def _article_text(article: dict) -> str:
    """Concatena todos los campos relevantes para el análisis temático."""
    parts: list[str] = []
    for key in ("title_original", "title_es", "summary_original", "summary_es",
                "short_headline_es", "short_caption_es", "region", "country",
                "source_name", "article_url", "canonical_url", "topic"):
        val = article.get(key)
        if val:
            parts.append(str(val))
    # tags / metadata opcionales
    tags = article.get("tags")
    if isinstance(tags, (list, tuple)):
        parts.extend(str(t) for t in tags)
    elif tags:
        parts.append(str(tags))
    meta = article.get("metadata")
    if isinstance(meta, dict):
        parts.extend(str(v) for v in meta.values())
    return _strip(" \n ".join(parts))


# --------------------------------------------------------------------------- #
def is_valid_tech_ai_news(article: dict,
                          config: Optional[dict] = None) -> tuple[bool, str, int]:
    """Filtro temático duro. Devuelve (es_valida, reason, topic_score).

    reason ∈ {"accepted", "not_tech", "political_general", "disabled"}.
    """
    cfg = config or {}
    if not cfg.get("enabled", True):
        return True, "disabled", 0

    min_score = int(cfg.get("min_topic_score", 2))
    positive = cfg.get("positive_keywords") or DEFAULT_POSITIVE
    negative = cfg.get("negative_keywords") or DEFAULT_NEGATIVE
    core = cfg.get("core_keywords") or DEFAULT_CORE

    text = _article_text(article)
    title_norm = _strip(f"{article.get('title_original','')} {article.get('title_es','')}")

    pos_found = _found(text, positive)
    core_found = _found(text, core)
    neg_found = _found(text, negative)

    # Núcleo cuenta doble: confirma con fuerza el tema tech/IA.
    topic_score = len(pos_found) + len(core_found)

    # Regla 3/4: si el título no tiene nada tech, exigimos que el núcleo aparezca
    # en algún lado (resumen/tags); si no hay núcleo ni positivos → no es tech.
    title_has_tech = bool(_found(title_norm, positive))

    accepted = (topic_score >= min_score) and (not neg_found or bool(core_found))
    # Si el título no es tech pero el cuerpo sí tiene núcleo, se permite (regla 3).
    if accepted and not title_has_tech and not core_found:
        accepted = False

    if accepted:
        return True, "accepted", topic_score

    # Rechazo: clasificar el motivo para el resumen.
    if neg_found:
        return False, "political_general", topic_score
    return False, "not_tech", topic_score


def log_decision(article: dict, valid: bool, reason: str, score: int) -> None:
    """Loguea la decisión con las etiquetas pedidas."""
    title = (article.get("title_original") or article.get("title_es") or "")[:70]
    if valid:
        log.info(f"[green][ACEPTADA TECH/IA][/] (t{score}) {title}")
    elif reason == "political_general":
        log.info(f"[red][RECHAZADA POLÍTICA][/] (t{score}) {title}")
    else:
        log.info(f"[yellow][RECHAZADA NO TECH][/] (t{score}) {title}")
