"""card_renderer.py — genera slide.png (1080x1350) por noticia.

Opción preferida (más elegante y flexible):
    Jinja2 (card_template.html) -> Playwright abre el HTML -> screenshot a PNG.

Fallback automático (si Playwright/navegador no está disponible):
    Pillow dibuja el slide (gradiente tecnológico + imagen opcional + texto).

Así el sistema NUNCA se queda sin slide.png aunque no haya navegador instalado.
"""
from __future__ import annotations

import base64
import html as html_lib
import mimetypes
import re
import textwrap
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import Article
from .utils import get_logger

log = get_logger()

SLIDE_W, SLIDE_H = 1080, 1350

# Palabras clave que se resaltan en violeta en el titular
_HL_KEYWORDS = [
    "inteligencia artificial", "artificial intelligence", "ia", "ai",
    "machine learning", "deep learning", "chatgpt", "openai", "anthropic",
    "claude", "gemini", "robot", "robótica", "robotica", "robotics", "chip",
    "chips", "gpu", "nvidia", "cuántica", "cuantica", "quantum", "modelo",
    "modelos", "algoritmo", "startup", "tecnología", "tecnologia", "ciencia",
]


def _data_uri_for_image(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    mime = mimetypes.guess_type(str(p))[0] or "image/jpeg"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def highlight_keywords(headline: str) -> str:
    """Escapa el titular y envuelve palabras clave en <span class='hl'>."""
    safe = html_lib.escape(headline or "")
    # Ordenar por longitud desc para no romper subcadenas
    for kw in sorted(_HL_KEYWORDS, key=len, reverse=True):
        pattern = re.compile(rf"(?<![\w])({re.escape(kw)})(?![\w])", re.IGNORECASE)
        safe = pattern.sub(r"<span class='hl'>\1</span>", safe, count=1)
    return safe


def _dynamic_headline_size(headline: str) -> int:
    n = len(headline or "")
    if n <= 40:
        return 84
    if n <= 70:
        return 74
    if n <= 100:
        return 64
    return 56


class CardRenderer:
    def __init__(self, settings: dict, templates_dir: str = "templates"):
        self.templates_dir = Path(templates_dir)
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
        )
        pw = (settings or {}).get("playwright", {})
        self.pw_enabled = pw.get("enabled", True)
        self.pw_headless = pw.get("headless", True)
        self._browser = None
        self._pw_ctx = None
        self._pw_failed = False

    # ------------------------------------------------------------------ #
    def build_card_html(self, article: Article, image_path: Optional[str]) -> str:
        data_uri = _data_uri_for_image(image_path)
        headline = (article.short_headline_es or article.title_es
                    or article.title_original)
        caption = (article.short_caption_es or article.summary_es
                   or article.summary_original or "")
        if len(caption) > 240:
            caption = caption[:237].rstrip() + "…"
        tpl = self.env.get_template("card_template.html")
        return tpl.render(
            headline_html=highlight_keywords(headline),
            headline_size=_dynamic_headline_size(headline),
            caption=caption,
            source_name=article.source_name,
            date=(article.published_at or "")[:10],
            category="IA" if article.media_type == "video" else "TECH",
            media_type=article.media_type,
            has_image=bool(data_uri),
            image_data_uri=data_uri or "",
        )

    # ------------------------------------------------------------------ #
    def render_slide(self, article: Article, image_path: Optional[str],
                     out_png: str | Path) -> bool:
        """Renderiza el slide. Devuelve True si se creó slide.png."""
        out_png = Path(out_png)
        html = self.build_card_html(article, image_path)
        # guardamos también el card.html final usado
        try:
            (out_png.parent / "card.html").write_text(html, encoding="utf-8")
        except Exception:
            pass

        if self.pw_enabled and not self._pw_failed:
            if self._render_with_playwright(html, out_png):
                return True
        # Fallback Pillow
        return self._render_with_pillow(article, image_path, out_png)

    # ----------------------- Playwright ------------------------------- #
    def _ensure_browser(self) -> bool:
        if self._browser is not None:
            return True
        try:
            from playwright.sync_api import sync_playwright
            self._pw_ctx = sync_playwright().start()
            self._browser = self._pw_ctx.chromium.launch(headless=self.pw_headless)
            return True
        except Exception as exc:
            log.warning(f"[yellow]Playwright no disponible para render "
                        f"({exc}); se usa Pillow.[/]")
            self._pw_failed = True
            return False

    def _render_with_playwright(self, html: str, out_png: Path) -> bool:
        if not self._ensure_browser():
            return False
        try:
            page = self._browser.new_page(
                viewport={"width": SLIDE_W, "height": SLIDE_H},
                device_scale_factor=1,
            )
            page.set_content(html, wait_until="networkidle")
            try:
                page.wait_for_timeout(400)
            except Exception:
                pass
            out_png.parent.mkdir(parents=True, exist_ok=True)
            el = page.query_selector(".slide")
            if el:
                el.screenshot(path=str(out_png))
            else:
                page.screenshot(path=str(out_png),
                                clip={"x": 0, "y": 0, "width": SLIDE_W, "height": SLIDE_H})
            page.close()
            return out_png.exists()
        except Exception as exc:
            log.warning(f"[yellow]Screenshot Playwright falló ({exc}); "
                        f"se usa Pillow.[/]")
            self._pw_failed = True
            return False

    # ----------------------- Pillow ----------------------------------- #
    def _render_with_pillow(self, article: Article, image_path: Optional[str],
                            out_png: Path) -> bool:
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageFilter
        except Exception as exc:
            log.error(f"No hay Playwright ni Pillow; no se puede crear slide.png ({exc})")
            return False

        W, H = SLIDE_W, SLIDE_H
        img = Image.new("RGB", (W, H), (10, 14, 26))

        # Fondo: imagen recortada arriba o gradiente tecnológico
        if image_path and Path(image_path).exists():
            try:
                hero = Image.open(image_path).convert("RGB")
                hero = self._cover(hero, W, 800)
                img.paste(hero, (0, 0))
            except Exception:
                self._paint_gradient(img)
        else:
            self._paint_gradient(img)

        draw = ImageDraw.Draw(img, "RGBA")
        # Scrim degradado oscuro inferior
        scrim_top = 520
        for y in range(scrim_top, H):
            alpha = int(250 * (y - scrim_top) / (H - scrim_top))
            draw.line([(0, y), (W, y)], fill=(8, 11, 22, min(alpha, 250)))

        f_brand = self._font(28, bold=True)
        f_head = self._font(_dynamic_headline_size(
            article.short_headline_es or article.title_es or article.title_original) - 4, bold=True)
        f_cap = self._font(32)
        f_foot = self._font(28, bold=True)

        margin = 64
        # Marca arriba
        draw.ellipse([margin, 60, margin + 18, 78], fill=(124, 58, 237, 255))
        draw.text((margin + 30, 56), "TECH · IA", font=f_brand, fill=(255, 255, 255, 255))

        # Titular (desde abajo)
        headline = (article.short_headline_es or article.title_es
                    or article.title_original or "").upper()
        cap = (article.short_caption_es or article.summary_es
               or article.summary_original or "")

        head_lines = self._wrap(draw, headline, f_head, W - 2 * margin)
        cap_lines = self._wrap(draw, cap, f_cap, W - 2 * margin)[:4]

        line_h_head = f_head.size + 12
        line_h_cap = f_cap.size + 10
        footer_h = 70
        block_h = len(head_lines) * line_h_head + 24 + len(cap_lines) * line_h_cap + footer_h
        y = H - margin - block_h

        for ln in head_lines:
            draw.text((margin, y), ln, font=f_head, fill=(255, 255, 255, 255))
            y += line_h_head
        y += 24
        for ln in cap_lines:
            draw.text((margin, y), ln, font=f_cap, fill=(215, 222, 240, 255))
            y += line_h_cap

        # Footer: línea + fuente + fecha
        y += 8
        draw.line([(margin, y), (W - margin, y)], fill=(255, 255, 255, 40), width=2)
        y += 16
        tag = "▶ " if article.media_type == "video" else ""
        draw.text((margin, y), f"{tag}{article.source_name}", font=f_foot,
                  fill=(255, 255, 255, 255))
        date = (article.published_at or "")[:10]
        if date:
            dw = draw.textlength(date, font=f_foot)
            draw.text((W - margin - dw, y), date, font=f_foot, fill=(159, 176, 208, 255))

        out_png.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_png, "PNG")
        return out_png.exists()

    # ----------------------- helpers Pillow --------------------------- #
    @staticmethod
    def _cover(im, w, h):
        from PIL import Image
        sw, sh = im.size
        scale = max(w / sw, h / sh)
        im = im.resize((int(sw * scale), int(sh * scale)), Image.LANCZOS)
        nw, nh = im.size
        left = (nw - w) // 2
        top = (nh - h) // 2
        return im.crop((left, top, left + w, top + h))

    @staticmethod
    def _paint_gradient(img):
        W, H = img.size
        px = img.load()
        for y in range(H):
            t = y / H
            r = int(19 + (10 - 19) * t)
            g = int(26 + (14 - 26) * t)
            b = int(53 + (26 - 53) * t)
            for x in range(0, W, 2):
                px[x, y] = (r, g, b)
                if x + 1 < W:
                    px[x + 1, y] = (r, g, b)
        # toque violeta arriba-izquierda
        from PIL import ImageDraw
        d = ImageDraw.Draw(img, "RGBA")
        d.ellipse([-200, -200, 600, 500], fill=(124, 58, 237, 60))
        d.ellipse([W - 500, -150, W + 200, 450], fill=(29, 78, 216, 50))

    def _font(self, size, bold=False):
        from PIL import ImageFont
        candidates = [
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
             else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            ("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf"),
            ("/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf"),
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
        return ImageFont.load_default()

    @staticmethod
    def _wrap(draw, text, font, max_w):
        if not text:
            return []
        words = text.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if draw.textlength(test, font=font) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    # ------------------------------------------------------------------ #
    def close(self):
        try:
            if self._browser:
                self._browser.close()
            if self._pw_ctx:
                self._pw_ctx.stop()
        except Exception:
            pass
