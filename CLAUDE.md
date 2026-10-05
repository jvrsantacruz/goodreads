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
SHELFMARK_API_KEY=... python goodreads.py follow want
```

### Run with Docker
```sh
./build.sh                 # Build Docker image
./run.sh list read         # Print read books as JSON
./render-all.sh            # Render both shelves to ~/notes/me
```

### Config
`config.json` (git-ignored) must exist with Goodreads RSS feed URLs, or pass `--config-json '{"read_url":...,"want_url":...}'` on the CLI.
Options go after the subcommand: `list read --config-json ...`.

`follow` also needs `shelfmark_url` and `shelfmark_user_id` in the config, and the
`SHELFMARK_API_KEY` environment variable. Both keys are optional, so the Action's config is
unchanged.

### Tests
```sh
make test   # pytest, through uv
make lint   # ruff and vulture
```

## Architecture

The entire application is a single file: `goodreads.py`.

**Data flow:**
1. Fetch Goodreads RSS feed pages (paginated) via `requests`
2. Parse XML using `xml.dom.pulldom` (streaming pull parser); strip HTML from field values with BeautifulSoup
3. Cache result as `data/books-{read|want}-{YYYY-MM-DD}.json` (one file per day, never overwritten)
4. On subsequent runs the same day, read from cache instead of fetching

**Three modes:**
- `list` — prints books as JSON to stdout
- `render` — updates Markdown files in `--books-dir` and writes summary lists to `--listas-dir`
- `follow` — files each book not filed yet as an ask in Shelfmark's request queue

**Follow behavior** (spec: `goodreads-intent` in the tech vault):
- One `POST /api/requests` per book, as Shelfmark's `manual` book, on behalf of `shelfmark_user_id`
- Filed Goodreads book IDs are kept in `data/filed-{id}.json`, written after each ask Shelfmark takes
- An ask Shelfmark already holds pending (`duplicate_pending_request`) is recorded as filed
- A refused ask is not recorded, so the next run retries it; the run then exits 1
- At the person's limit of waiting asks (`409 max_pending_reached`) the run stops and exits 0; the rest are `deferred` to a later run
- A failed feed page raises, so a partial shelf files nothing
- One summary line per run: `follow want: seen=N filed=N pending=N refused=N deferred=N`

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
