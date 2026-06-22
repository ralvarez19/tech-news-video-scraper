"""Render diario de la intro con fecha superpuesta.

Usa ``assets/intro.png`` como plantilla y genera una copia por run, sin tocar
la imagen base.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from .utils import get_logger, load_yaml

log = get_logger()

SETTINGS_PATH = "config/settings.yaml"

MONTHS_ES = {
    1: "enero",
    2: "febrero",
    3: "marzo",
    4: "abril",
    5: "mayo",
    6: "junio",
    7: "julio",
    8: "agosto",
    9: "septiembre",
    10: "octubre",
    11: "noviembre",
    12: "diciembre",
}

DAYS_ES = {
    0: "lunes",
    1: "martes",
    2: "miércoles",
    3: "jueves",
    4: "viernes",
    5: "sábado",
    6: "domingo",
}


def render_intro_with_date(run_output_dir: str, settings: dict[str, Any] | None = None) -> str:
    """
    Toma assets/intro.png, le agrega la fecha del dia y devuelve la ruta de la
    imagen generada.
    """
    cfg = (settings or load_yaml(SETTINGS_PATH)).get("intro", {})
    if not cfg.get("enabled", True):
        return ""

    base_image = Path(cfg.get("base_image", "assets/intro.png"))
    if not base_image.exists():
        log.warning(f"[yellow]Intro base no encontrada: {base_image}[/]")
        return ""

    run_dir = Path(run_output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out_path = run_dir / cfg.get("output_name", "intro_rendered.png")

    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
    except Exception as exc:
        log.warning(f"[yellow]Pillow no disponible; no se genero intro diaria ({exc}).[/]")
        return ""

    try:
        image = Image.open(base_image).convert("RGBA")
        draw = ImageDraw.Draw(image, "RGBA")
        text = _date_text(cfg) if cfg.get("add_date", True) else ""
        if not text:
            image.convert("RGB").save(out_path, "PNG")
            return str(out_path)

        font = _font(cfg, int(cfg.get("font_size", 42)))
        color = _hex_to_rgba(cfg.get("font_color", "#FFFFFF"))
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x, y = _position(text_w, text_h, image.size, cfg)

        if cfg.get("background", False):
            padding_x = int(cfg.get("background_padding_x", 26))
            padding_y = int(cfg.get("background_padding_y", 14))
            bg_color = _hex_to_rgba(cfg.get("background_color", "#000000"), alpha=120)
            draw.rounded_rectangle(
                [x - padding_x, y - padding_y, x + text_w + padding_x, y + text_h + padding_y],
                radius=int(cfg.get("background_radius", 18)),
                fill=bg_color,
            )

        if cfg.get("shadow", True):
            shadow_color = _hex_to_rgba(cfg.get("shadow_color", "#000000"), alpha=180)
            sx = int(cfg.get("shadow_offset_x", 2))
            sy = int(cfg.get("shadow_offset_y", 2))
            blur = int(cfg.get("shadow_blur", 2))
            if blur > 0:
                shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
                ImageDraw.Draw(shadow, "RGBA").text(
                    (x + sx, y + sy), text, font=font, fill=shadow_color
                )
                image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(blur)))
            else:
                draw.text((x + sx, y + sy), text, font=font, fill=shadow_color)

        ImageDraw.Draw(image, "RGBA").text((x, y), text, font=font, fill=color)
        image.convert("RGB").save(out_path, "PNG")
        log.info(f"[green]Intro diaria generada:[/] {out_path}")
        return str(out_path)
    except Exception as exc:
        log.warning(f"[yellow]No se pudo generar la intro diaria: {exc}[/]")
        return ""


def _date_text(cfg: dict[str, Any]) -> str:
    fmt = str(cfg.get("date_format", "%d de %B de %Y"))
    today = datetime.now()
    if str(cfg.get("locale", "es")).lower().startswith("es"):
        return _strftime_es(today, fmt)
    return today.strftime(fmt)


def _strftime_es(dt: datetime, fmt: str) -> str:
    replacements = {
        "%B": ("__TNVS_MONTH_FULL__", MONTHS_ES[dt.month]),
        "%b": ("__TNVS_MONTH_SHORT__", MONTHS_ES[dt.month][:3]),
        "%A": ("__TNVS_DAY_FULL__", DAYS_ES[dt.weekday()].capitalize()),
        "%a": ("__TNVS_DAY_SHORT__", DAYS_ES[dt.weekday()][:3].capitalize()),
    }
    protected = fmt
    for token, (placeholder, _value) in replacements.items():
        protected = protected.replace(token, placeholder)
    text = dt.strftime(protected)
    for _token, (placeholder, value) in replacements.items():
        text = text.replace(placeholder, value)
    return text


def _position(text_w: int, text_h: int, size: tuple[int, int], cfg: dict[str, Any]) -> tuple[int, int]:
    w, h = size
    margin_x = int(cfg.get("margin_x", round(w * 0.07)))
    margin_y = int(cfg.get("margin_y", round(h * 0.07)))
    pos = str(cfg.get("text_position", "bottom_center")).lower()
    positions = {
        "top_left": (margin_x, margin_y),
        "top_center": ((w - text_w) // 2, margin_y),
        "top_right": (w - margin_x - text_w, margin_y),
        "center": ((w - text_w) // 2, (h - text_h) // 2),
        "bottom_left": (margin_x, h - margin_y - text_h),
        "bottom_center": ((w - text_w) // 2, h - margin_y - text_h),
        "bottom_right": (w - margin_x - text_w, h - margin_y - text_h),
    }
    x, y = positions.get(pos, positions["bottom_center"])
    x += int(cfg.get("offset_x", 0))
    y += int(cfg.get("offset_y", 0))
    return max(0, x), max(0, y)


def _font(cfg: dict[str, Any], size: int):
    from PIL import ImageFont

    candidates = [
        cfg.get("font_path"),
        "assets/fonts/Inter-SemiBold.ttf",
        "assets/fonts/Inter-Bold.ttf",
        "assets/fonts/Montserrat-SemiBold.ttf",
        "C:/Windows/Fonts/segoeuisb.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ]
    for path in candidates:
        if not path:
            continue
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _hex_to_rgba(value: str, alpha: int = 255) -> tuple[int, int, int, int]:
    text = str(value or "#FFFFFF").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) == 8:
        alpha = int(text[6:8], 16)
        text = text[:6]
    try:
        return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), alpha
    except Exception:
        return 255, 255, 255, alpha
