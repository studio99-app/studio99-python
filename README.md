# studio99-python

[![PyPI](https://img.shields.io/pypi/v/studio99)](https://pypi.org/project/studio99/)

Official Python client for the **Studio99 Indic Typography API**: exact Hindi, Marathi, Gujarati and English text as editable SVG and PNG, from real calligraphy fonts.

- Standard library only (no dependencies), Python 3.9+
- Server-side use: keep your API key on your server

## Install

```bash
pip install studio99
```

Get an API key at https://accounts.studio99.app/dashboard/products/studio99-api (Free plan: 100 credits a month, watermarked previews).

## Quick start

```python
from studio99 import Studio99

s99 = Studio99()  # reads STUDIO99_API_KEY

res = s99.generate(
    "shubh vivah",          # Latin letters are transliterated; Devanagari/Gujarati work as-is
    language="hindi",
    use_case="wedding",
    count=4,                # 1 credit per variant
)

for i, variant in enumerate(res.data["generatedResults"], 1):
    if variant.get("svg"):
        with open(f"variant-{i}.svg", "w", encoding="utf-8") as f:
            f.write(variant["svg"]["svgString"])   # complete, editable SVG

print("Credits left:", res.usage["remaining"])
```

## Methods

| Method | Endpoint | Cost |
|---|---|---|
| `generate(text, **options)` | `POST /generate` | 1 credit per variant |
| `render(text, font_id, font_size=, format=, png_width=)` | `POST /render` | 1 credit |
| `fonts(language=, mood=, use_case=, limit=)` | `GET /fonts` | free |
| `library.search(q, category=, language=, page=, limit=)` | `GET /library/search` | free |
| `library.get(id)` | `GET /library/{id}` | free |
| `library.download(id, format="PNG")` | `GET /library/{id}/download` | 1 credit |
| `library.render_svg(id)` | `GET /library/{id}/render-svg` | 1 credit |
| `capabilities()`, `health()` | meta | free |

Every method returns a `Response` with `.data`, `.usage` and `.rate_limit`. `generate` options use the API's own field names (`language`, `count`, `format`, `pngWidth`, `fontId`, `use_case`, `mood`, `align`, `lines`, `seed`, ...); see the [OpenAPI spec](https://github.com/studio99-app/openapi).

### Exact rendering in one font

```python
fonts = s99.fonts(language="marathi", mood="festive", limit=5).data["fonts"]
out = s99.render("दिवाळीच्या शुभेच्छा", fonts[0]["id"], format="svg").data
print(out["svgString"])
```

### Free plan

Free-plan calls return a small watermarked JPG in `preview` (no commercial licence) instead of `svg`/`png`.

## Errors and retries

Failed calls raise `Studio99Error` with `.code` (API error code such as `INSUFFICIENT_CREDITS`, `TEXT_TOO_LONG`, `FONT_NOT_FOUND`), `.status` and `.rate_limit`.

`RATE_LIMIT_EXCEEDED` is retried after the reset time (rate-limited calls are not charged). GET requests are also retried on network errors and 502-504. `generate` and `render` calls that may have reached the engine are **never** retried automatically, so you are never charged twice. Tune with `Studio99(max_retries=..., timeout=...)`.

## Keep your key safe

Keep it in an environment variable on your server; never commit it or put it in a browser or mobile app. `repr(client)` never prints the key. A revoked key stops working within a minute.

## Links

[Docs](https://studio99.app/developers/docs) · [Pricing](https://studio99.app/developers/pricing) · [Changelog](https://studio99.app/developers/changelog) · [Status](https://studio99.app/developers/status) · [API terms](https://studio99.app/developers/terms) · [Examples](https://github.com/studio99-app/examples)

## Licence

This client: MIT. The API, its fonts and the artwork it returns are governed by the [API terms](https://studio99.app/developers/terms); the fonts are proprietary and never leave our servers.

Built by [ArtoMania Studio](https://artomaniastudio.com), Pune · reach@studio99.app
