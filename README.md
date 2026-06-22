# Tech News Video Scraper + generador de carruseles

Aplicación local en Python que busca noticias **recientes** sobre **tecnología,
inteligencia artificial, robótica, ciencia aplicada, chips, software y empresas
tecnológicas**, las puntúa, las guarda en **SQLite** y genera por cada noticia
una **pieza visual final `slide.png` (1080×1350)** lista para publicar como
**carrusel de Instagram** estilo tecnológico/premium, además de una galería
`index.html` para revisarlas todas.

> Pensada como **MVP local para Windows**, con arquitectura modular para luego
> integrarse con una **API FastAPI** o una **app Flutter**.

---

## Características

- Pregunta el **tema** al iniciar (ENTER = *tecnología e inteligencia artificial*).
- Configurable: número de noticias (por defecto **5**) e idioma de salida (por defecto **español**).
- Busca en **múltiples fuentes globales** definidas en `config/sources.yaml` (RSS o HTML).
- **Genera una intro diaria con fecha** desde `assets/intro.png`, guardada como
  `intro_rendered.png` dentro de cada run.
- **Genera `slide.png` real por noticia** (1080×1350) — *no se queda en `card.html` sin renderizar*.
- **Prioriza noticias con video**; si no completa las N pedidas, **rellena con
  noticias de imagen de alta calidad** (`media_type: image`).
- Detecta video por: `<video>`, iframes (YouTube/Vimeo/Dailymotion…), Open Graph, JSON-LD y embeds.
- **Comprueba si el video es embebible** (cabeceras `X-Frame-Options`/`CSP`). Si
  está bloqueado (caso B), **no falla**: guarda el enlace + `video_poster.jpg` y
  usa esa imagen en el slide, marcando `embed_status: blocked` y el motivo.
- **Filtro temático DURO (Tech/IA)** antes del ranking y de guardar/exportar:
  si no es tecnología/IA, **no entra**. Rechaza política general, economía,
  deportes, crimen, farándula, etc. (acepta política/regulación **solo** si está
  ligada a IA/tecnología, p. ej. regulación de IA o ley de chips).
- **Traducción** modular al español (título, descripción, titular y caption cortos para el slide).
- **Ranking** con puntuación para elegir las mejores noticias (con *gate*: nada
  que no pase el filtro llega al top 5).
- **Deduplicación** por `canonical_url`, `article_url` y hash de título.
- Galería `index.html` + `summary.json` + `summary.txt` por ejecución.
- **Envío automático a Telegram** de la intro, los 5 slides y el outro al finalizar
  (opcional, por `.env`).
- Respeta `robots.txt`. **No** salta paywalls, captchas, logins ni DRM. Guarda
  enlaces/embeds de video de terceros (no descarga videos protegidos).

## Filtro temático (Tech/IA)

Implementado en `src/topic_filter.py` y configurable en `config/settings.yaml`
bajo `topic_filter` (`enabled`, `min_topic_score`, `positive_keywords`,
`negative_keywords`). Por cada noticia loguea la decisión:
`[ACEPTADA TECH/IA]`, `[RECHAZADA NO TECH]` o `[RECHAZADA POLÍTICA]`. Las
rechazadas no se guardan en SQLite ni generan slide.

## Envío a Telegram

1. Copia `.env.example` a `.env` y rellena tus datos:

   ```env
   TELEGRAM_ENABLED=true
   TELEGRAM_BOT_TOKEN=tu_token_de_BotFather
   TELEGRAM_CHAT_ID=tu_chat_id
   TELEGRAM_SEND_AS_ALBUM=true
   ```

2. Al finalizar, el programa envía la intro diaria, los `slide.png` generados y
   `assets/out.png` como outro cuando existe. Si
   `TELEGRAM_SEND_AS_ALBUM=true` usa `sendMediaGroup` (álbum); si falla, envía
   uno por uno con `sendPhoto`. Cada slide lleva un caption con número, título,
   fuente y enlace al artículo.

   - Si faltan variables: `[TELEGRAM] No configurado. Se omite envío.`
   - Si está desactivado: `[TELEGRAM] Desactivado por TELEGRAM_ENABLED=false`
   - Si todo va bien: `[TELEGRAM] Slides enviados correctamente.`

   El archivo `.env` **no** se sube al repositorio (está en `.gitignore`).

## Cómo se genera el `slide.png`

1. **Opción preferida (más elegante):** `card_template.html` (Jinja2 + CSS) se
   abre con **Playwright** y se captura un screenshot exacto a 1080×1350. Incluye
   imagen de fondo, degradado oscuro, titular en MAYÚSCULAS con **palabras clave
   en violeta** y footer con fuente + fecha.
2. **Fallback automático (sin navegador):** si Playwright no está instalado, se
   dibuja el slide con **Pillow** (gradiente tecnológico + imagen + texto). Así
   el sistema **nunca** se queda sin `slide.png`.

> Para el resultado visual completo (palabras clave en violeta, imagen de fondo
> nítida) ejecuta `playwright install` una vez. Sin él, el fallback Pillow sigue
> produciendo un slide limpio y usable.

## Intro diaria con fecha

En cada ejecución, el flujo crea primero una intro diaria a partir de
`assets/intro.png` y la guarda sin reemplazar el original:

```text
output/YYYY-MM-DD_HH-mm-ss/intro_rendered.png
```

La ruta también queda registrada en `summary.json`, `summary.txt` y aparece al
inicio de la galería `index.html`. El orden del flujo visual queda:

1. intro diaria con fecha;
2. slides de noticias;
3. outro (`assets/out.png`, si existe);
4. exportación y envío a Telegram, si está configurado.

La configuración está en `config/settings.yaml`, sección `intro`:

```yaml
intro:
  enabled: true
  base_image: "assets/intro.png"
  output_name: "intro_rendered.png"
  add_date: true
  date_format: "%d de %B de %Y"
  locale: "es"
  text_position: "bottom_center"
  font_size: 42
  font_color: "#FFFFFF"
  shadow: true
```

Para cambiar el texto usa `date_format`, por ejemplo
`"Noticias de hoy · %d de %B de %Y"` o `"%A, %d de %B de %Y"`. Los nombres de
meses y días se generan en español aunque el locale del sistema no esté
configurado. Para moverlo cambia `text_position` (`bottom_center`,
`top_right`, etc.) y ajusta `margin_x`, `margin_y`, `offset_x` u `offset_y`.
Para el estilo visual puedes cambiar `font_color`, `font_size`, `shadow_*` o
definir `font_path` apuntando a una tipografía dentro de `assets/fonts/`.

---

## Requisitos

- Python 3.10+ (probado con 3.10).
- Windows (las instrucciones usan PowerShell), aunque funciona en macOS/Linux.

---

## Instalación (Windows PowerShell)

```powershell
cd C:\ProyectosIA\tech-news-video-scraper
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install
python app.py
```

> `playwright install` solo es necesario si quieres renderizado dinámico para
> páginas que cargan el video por JavaScript. Si no lo instalas, el programa
> seguirá funcionando con `requests` + `BeautifulSoup` y RSS.

### Uso

```powershell
# Interactivo (pregunta tema, número e idioma)
python app.py

# Directo, sin preguntar
python app.py --topic "robótica e inteligencia artificial" --num 5 --lang es --no-input
```

Argumentos:

| Flag         | Descripción                              | Por defecto |
|--------------|------------------------------------------|-------------|
| `--topic`    | Tema de búsqueda                         | tecnología e IA |
| `--num`      | Número de noticias a generar             | 5           |
| `--lang`     | Idioma de salida                         | es          |
| `--no-input` | No preguntar; usar valores por defecto   | —           |

---

## Estructura del proyecto

```
tech_news_video_scraper/
├── app.py                 # Orquestador CLI
├── requirements.txt
├── README.md
├── config/
│   ├── sources.yaml       # Fuentes (agregar/quitar aquí)
│   └── settings.yaml      # Configuración general
├── assets/
│   ├── intro.png          # Plantilla base de la intro diaria
│   └── out.png            # Outro opcional enviado al final por Telegram
├── data/
│   └── news.db            # Base SQLite (se crea sola)
├── output/                # Carpetas de salida por ejecución
├── templates/
│   ├── card_template.html   # Slide 1080x1350 (Jinja2 + CSS) → screenshot
│   ├── embed_template.html  # Reproductor / fallback a poster
│   ├── index_template.html  # Galería del run
│   └── card.html            # (plantilla heredada, opcional)
└── src/
    ├── __init__.py
    ├── database.py        # Esquema SQLite + deduplicación + migración
    ├── models.py          # Dataclasses (Article, Source, Run)
    ├── scraper.py         # Descarga listados/artículos (requests + Playwright)
    ├── source_loader.py   # Carga sources.yaml
    ├── video_detector.py  # Detección de video
    ├── media_extractor.py # Hero image, poster, chequeo de embed, descargas
    ├── card_renderer.py   # Render del slide.png (Playwright + fallback Pillow)
    ├── intro_renderer.py  # Render de intro diaria con fecha sobre assets/intro.png
    ├── topic_filter.py    # Filtro DURO Tech/IA (antes de guardar/exportar)
    ├── telegram_sender.py # Envío de intro, slides y outro a Telegram (.env)
    ├── translator.py      # Traducción modular
    ├── ranker.py          # Puntuación / selección (con gate del filtro)
    ├── exporter.py        # Genera carpetas, slides, index/summary
    └── utils.py           # Hash, fechas, logging, URLs
```

---

## Salida generada

Por cada ejecución se crea:

```
output/2026-06-17_14-30-05/
├── index.html           # Galería con las 5 noticias (preview de cada slide)
├── intro_rendered.png   # Intro diaria generada desde assets/intro.png
├── summary.json         # Resumen estructurado del run + estadísticas
├── summary.txt          # Resumen legible
├── noticia_01/
│   ├── slide.png        # ★ PIEZA VISUAL FINAL 1080x1350 (carrusel)
│   ├── card.html        # HTML usado para generar el slide
│   ├── embed.html       # Reproductor del video (o fallback a poster)
│   ├── video_poster.jpg # Miniatura/poster del video (si existe)
│   ├── hero_image.jpg   # Imagen principal del artículo (si existe)
│   ├── metadata.json    # Metadatos + puntuación + embed_status
│   ├── noticia.json     # Objeto completo de la noticia
│   ├── noticia.txt      # Resumen legible
│   ├── source.url       # Acceso directo a la noticia
│   ├── video.url        # Acceso directo al video
│   ├── video_url.txt    # Enlace directo del video (caso B, no embebible)
│   └── README.txt
├── noticia_02/
└── ...
```

### Comportamiento del video

- **Caso A — video embebible:** `embed.html` muestra el reproductor; se guarda
  `video_embed_url` y `video_type`; `embed_status: ok`.
- **Caso B — video bloqueado** (`X-Frame-Options`/`CSP`/DRM): **no falla**. Se
  guarda `video_url.txt` + `video_poster.jpg`, se usa el poster en `slide.png`,
  y en `metadata.json` queda `embed_status: blocked` con el motivo.
- **Caso C — sin video pero con imagen:** se permite si la noticia es de alta
  calidad (entra en las mejores); `media_type: image`, se usa `hero_image.jpg`
  en el slide.

El slide está diseñado a **1080×1350 (4:5 vertical)** para carrusel de Instagram.

---

## Cómo agregar nuevas fuentes

Edita `config/sources.yaml` y añade un bloque. Lo más estable es usar **RSS**:

```yaml
  - name: "Mi Fuente Tech"
    enabled: true
    trusted: false           # true suma puntos en el ranking
    region: "Global"
    rss: "https://ejemplo.com/feed"        # preferido si existe
    listing_urls:
      - "https://ejemplo.com/tecnologia"   # alternativa: portada de sección
    article_pattern: "/articulo/"          # filtra qué URLs son artículos
    needs_js: false                        # true si necesita Playwright
```

- Si la fuente tiene **RSS**, rellena `rss` (más respetuoso y fiable).
- Si no, usa `listing_urls` + `article_pattern` (substring que aparece en las
  URLs de artículos reales, para filtrar menús/etiquetas).
- `needs_js: true` solo si la página carga el contenido/video con JavaScript.
- Para **desactivar** una fuente sin borrarla: `enabled: false`.

Las fuentes con `trusted: true` se intentan **primero**.

---

## Configuración (settings.yaml)

Lo más relevante:

- `defaults.topic / num_news / language` — valores por defecto.
- `search.max_age_days` — descarta noticias más viejas (0 = sin límite).
- `search.respect_robots_txt` — respeta `robots.txt`.
- `video.require_video` — exige video en cada noticia.
- `translation.api` — rellena `provider` (`deepl`/`google`) y `api_key` para usar
  una API; si lo dejas vacío, se usa el fallback gratuito `deep-translator`.
- `ranking.weights` — pesos de la puntuación.

### Traducción

1. **Con API** (mejor calidad): instala el SDK correspondiente
   (`pip install deepl` o `google-cloud-translate`) y rellena `translation.api`.
2. **Sin API** (por defecto): usa `deep-translator` (Google gratuito). Si no
   está disponible, los textos se guardan en su idioma original sin romper el flujo.

---

## Esquema SQLite (resumen)

- **runs**: una fila por ejecución (tema, idioma, contadores, carpeta).
- **sources**: fuentes vistas (nombre, confiable, región).
- **articles**: una fila por noticia guardada, con todos los campos
  (`title_original`, `title_es`, `summary_es`, `language_original`, `video_url`,
  `video_embed_url`, `video_type`, `published_at`, `content_hash`, `status`,
  `output_folder`, …) e índices para deduplicación.

---

## Buenas prácticas y límites legales

- No se evaden paywalls, captchas, autenticación ni DRM.
- Se respeta `robots.txt` cuando es accesible.
- No se descargan videos de terceros: se guarda el **enlace/embed público**.
- Úsalo de forma responsable y revisa los términos de uso de cada fuente.

---

## Integración futura (FastAPI / Flutter)

La lógica está separada de la CLI: `Database`, `Scraper`, `Translator`,
`Ranker` y `Exporter` son clases reutilizables. Para exponer una API basta con
envolver `run()` en un endpoint FastAPI y devolver los objetos `Article`
(ya serializables con `to_dict()`).
