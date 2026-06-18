# Tech News Video Scraper

Aplicación local en Python que busca noticias **recientes con video** sobre
**tecnología, inteligencia artificial, robótica, ciencia aplicada, chips,
software y empresas tecnológicas**, las puntúa, las guarda en una base de datos
local **SQLite** y exporta carpetas listas para publicar como **carrusel** en
redes sociales (descripción arriba, video embebido abajo).

> Pensada como **MVP local para Windows**, con arquitectura modular para luego
> integrarse con una **API FastAPI** o una **app Flutter**.

---

## Características

- Pregunta el **tema** al iniciar (ENTER = *tecnología e inteligencia artificial*).
- Configurable: número de noticias (por defecto **5**) e idioma de salida (por defecto **español**).
- Busca en **múltiples fuentes globales** definidas en `config/sources.yaml` (RSS o HTML).
- **Cada noticia debe tener video.** Si no lo tiene, se descarta y se busca otra.
- Detecta video por: `<video>`, iframes (YouTube/Vimeo/Dailymotion…), Open Graph, JSON-LD y embeds.
- **Traducción** modular al español (título y descripción; el video se deja en su idioma).
- **Ranking** con puntuación para elegir las mejores noticias.
- **Deduplicación** por `canonical_url`, `article_url` y hash de título.
- Carpeta de salida por ejecución con una subcarpeta por noticia.
- Respeta `robots.txt`. **No** salta paywalls, captchas, logins ni DRM. Guarda
  enlaces/embeds de video de terceros (no descarga videos protegidos).

---

## Requisitos

- Python 3.10+ (probado con 3.10).
- Windows (las instrucciones usan PowerShell), aunque funciona en macOS/Linux.

---

## Instalación (Windows PowerShell)

```powershell
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
├── data/
│   └── news.db            # Base SQLite (se crea sola)
├── output/                # Carpetas de salida por ejecución
├── templates/
│   └── card.html          # Plantilla de tarjeta vertical (Jinja2)
└── src/
    ├── __init__.py
    ├── database.py        # Esquema SQLite + deduplicación
    ├── models.py          # Dataclasses (Article, Source, Run)
    ├── scraper.py         # Descarga listados/artículos (requests + Playwright)
    ├── source_loader.py   # Carga sources.yaml
    ├── video_detector.py  # Detección de video
    ├── translator.py      # Traducción modular
    ├── ranker.py          # Puntuación / selección
    ├── exporter.py        # Genera carpetas y archivos
    └── utils.py           # Hash, fechas, logging, URLs
```

---

## Salida generada

Por cada ejecución se crea:

```
output/2026-06-17_14-30-05/
├── noticia_01/
│   ├── noticia.json     # Objeto completo de la noticia
│   ├── noticia.txt      # Resumen legible
│   ├── card.html        # Tarjeta vertical (descripción arriba, video abajo)
│   ├── embed.html       # Reproductor mínimo
│   ├── metadata.json    # Metadatos + puntuación
│   ├── source.url       # Acceso directo a la noticia
│   ├── video.url        # Acceso directo al video
│   └── README.txt
├── noticia_02/
└── ...
```

`noticia.txt` tiene este formato:

```
Título:
Descripción corta:
Fuente:
Fecha:
Link noticia:
Link video:
Texto para carrusel:
```

Para convertir una tarjeta en imagen/video vertical: abre `card.html` en el
navegador y captúrala (o automatízalo con una herramienta de captura). El marco
está diseñado a 1080×1920 (9:16).

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
