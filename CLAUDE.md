# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Run without Docker
```sh
pip install -r requirements.txt
python goodreads.py list read
python goodreads.py list want
python goodreads.py render read --listas-dir Listas/ --books-dir Libros/
python goodreads.py render want --listas-dir Listas/ --books-dir Libros/
```

### Run with Docker
```sh
./build.sh                 # Build Docker image
./run.sh list read         # Print read books as JSON
./render-all.sh            # Render both shelves to ~/notes/me
```

### Config
`config.json` (git-ignored) must exist with Goodreads RSS feed URLs, or pass `--config-json '{"read_url":...,"want_url":...}'` on the CLI.

### Tests
There are no automated tests.

## Architecture

The entire application is a single file: `goodreads.py`.

**Data flow:**
1. Fetch Goodreads RSS feed pages (paginated) via `requests`
2. Parse XML using `xml.dom.pulldom` (streaming pull parser); strip HTML from field values with BeautifulSoup
3. Cache result as `data/books-{read|want}-{YYYY-MM-DD}.json` (one file per day, never overwritten)
4. On subsequent runs the same day, read from cache instead of fetching

**Two output modes:**
- `list` — prints books as JSON to stdout
- `render` — updates Markdown files in `--books-dir` and writes summary lists to `--listas-dir`

**Render behavior:**
- Only updates `.md` files that already exist in `--books-dir`; does not create new book files
- `Book.name` (used as the filename stem) strips everything after `:` or `(` and removes `:`, `/`, `\` characters
- Author fields are written as Obsidian wiki-links: `[[Autores/{author}|{author}]]`
- Summary lists use Obsidian wiki-link syntax: `[[date]] ᐧ [[dir/book|book]]`

**Book file format** (critical for `save_file` / `extract_yaml_doc`):
```
---
key: value
...
---

#libro

----

<free-form notes>
```
- YAML block ends with `...` (ruamel `explicit_end=True`); `extract_yaml_doc` reads lines until `...\n`
- `extract_file_text` reads past the `----\n`-suffixed line and returns everything after it
- `save_file()` merges new metadata with existing YAML front matter (existing keys win), preserving the notes text

**Docker mounts (run.sh):**
- `./data` → `/data` (cache)
- `~/notes/me` → `/notes` (output)
- repo dir → `/app` (code)

**GitHub Actions:**
- `build.yml` — builds and pushes Docker image to `ghcr.io` on pushes to `master` that change `Dockerfile` or `.py` files
- `sync.yml` — runs twice daily (00:03 and 12:03 UTC), renders both shelves into a separate target repo (`jvrsantacruz/me`) and commits; requires `GOODREADS_CONFIG` secret (JSON string with feed URLs) and `ME_REPO_TOKEN` for push access
