# 0002 — Strip UTM tracking params from book URLs

**Status:** draft **·** **Owner:** jvr **·** **Updated:** 2026-06-28

## Why this exists

Goodreads RSS `link` values carry `utm_medium`/`utm_source` tracking params. Those are noise in the note's `url` front-matter field — we want the clean canonical URL.

## Functional requirements

- When building a `Book`, strip `utm_medium` and `utm_source` query params from `url`.
- Leave all other params and the rest of the URL untouched.

## Implementation hint

Strip in `Book.from_goodreads`. Sketch with `urllib.parse`:

```python
def strip_utm(url: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query)
             if k not in ("utm_medium", "utm_source")]
    return urlunsplit(parts._replace(query=urlencode(query)))
```

`...?utm_medium=api&utm_source=rss` → clean URL.
