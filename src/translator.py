"""translator.py — traducción modular al español.

Diseño:
  - Si hay una API configurada (DeepL o Google) en settings.yaml, se usa.
  - Si no, se intenta deep-translator (GoogleTranslator gratuito).
  - Si nada está disponible, se devuelve el texto original (fallback "none")
    marcando que no se tradujo, pero el programa NO se detiene.

La detección de idioma usa langdetect. El video se deja en su idioma original;
solo se traducen título y descripción.
"""
from __future__ import annotations

from typing import Optional

from .utils import get_logger

log = get_logger()


def detect_language(text: str) -> str:
    """Detecta el idioma de un texto (código ISO-639-1) o 'und' si falla."""
    if not text or len(text.strip()) < 3:
        return "und"
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 0
        return detect(text)
    except Exception:
        return "und"


class Translator:
    """Traductor con backend intercambiable."""

    def __init__(self, settings: dict):
        tr = (settings or {}).get("translation", {})
        self.target = tr.get("target_language", "es")
        self.backend_pref = tr.get("backend", "auto")
        api = tr.get("api", {}) or {}
        self.api_provider = (api.get("provider") or "").lower()
        self.api_key = api.get("api_key") or ""

        self._engine = None          # callable(text, src, dest) -> str
        self._backend_name = "none"
        self._init_backend()

    # ------------------------------------------------------------------ #
    def _init_backend(self) -> None:
        pref = self.backend_pref

        if pref == "none":
            self._backend_name = "none"
            return

        # 1) API explícita
        if self.api_provider == "deepl" and self.api_key:
            if self._try_deepl():
                return
        if self.api_provider == "google" and self.api_key:
            if self._try_google_cloud():
                return

        # 2) deep-translator (gratuito) como fallback
        if pref in ("auto", "deep_translator"):
            if self._try_deep_translator():
                return

        self._backend_name = "none"
        log.warning("[yellow]No hay backend de traducción disponible. "
                    "Los textos se guardarán en su idioma original.[/]")

    def _try_deepl(self) -> bool:
        try:
            import deepl  # type: ignore
            translator = deepl.Translator(self.api_key)

            def engine(text: str, src: str, dest: str) -> str:
                res = translator.translate_text(text, target_lang="ES")
                return str(res)

            self._engine = engine
            self._backend_name = "deepl"
            log.info("Traducción: usando API DeepL")
            return True
        except Exception as exc:
            log.debug(f"DeepL no disponible: {exc}")
            return False

    def _try_google_cloud(self) -> bool:
        try:
            from google.cloud import translate_v2 as gtranslate  # type: ignore
            client = gtranslate.Client()

            def engine(text: str, src: str, dest: str) -> str:
                res = client.translate(text, target_language=dest)
                return res["translatedText"]

            self._engine = engine
            self._backend_name = "google_cloud"
            log.info("Traducción: usando API Google Cloud Translation")
            return True
        except Exception as exc:
            log.debug(f"Google Cloud Translate no disponible: {exc}")
            return False

    def _try_deep_translator(self) -> bool:
        try:
            from deep_translator import GoogleTranslator

            def engine(text: str, src: str, dest: str) -> str:
                source = src if src and src != "und" else "auto"
                return GoogleTranslator(source=source, target=dest).translate(text)

            self._engine = engine
            self._backend_name = "deep_translator"
            log.info("Traducción: usando deep-translator (GoogleTranslator gratuito)")
            return True
        except Exception as exc:
            log.debug(f"deep-translator no disponible: {exc}")
            return False

    # ------------------------------------------------------------------ #
    @property
    def backend(self) -> str:
        return self._backend_name

    def translate(self, text: str, src_lang: str = "auto") -> str:
        """Traduce 'text' al idioma destino. Si no se puede, devuelve el original."""
        if not text or not text.strip():
            return text
        # Si ya está en el idioma destino, no traducir.
        if src_lang and src_lang.startswith(self.target):
            return text
        if not self._engine:
            return text
        try:
            # deep-translator/algunas APIs tienen límites por longitud; troceamos.
            if len(text) > 4500:
                parts = _chunk(text, 4500)
                return " ".join(self._safe(p, src_lang) for p in parts)
            return self._safe(text, src_lang)
        except Exception as exc:
            log.debug(f"Fallo de traducción, se mantiene original: {exc}")
            return text

    def _safe(self, text: str, src_lang: str) -> str:
        try:
            out = self._engine(text, src_lang, self.target)
            return out or text
        except Exception:
            return text


def _chunk(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]
