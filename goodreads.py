#!/usr/bin/env python3
"""

See: https://github.com/maria-antoniak/goodreads-scraper/blob/master/get_books.py
"""

import argparse
import io
import json
import os
import random
import re
import sys
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import cached_property, partial
from itertools import takewhile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
import ruamel.yaml
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util import Retry


class FollowConfigError(Exception):
    pass


class ShelfError(Exception):
    pass


@dataclass
class Config:
    read_url: str
    want_url: str
    # Only for `follow`: where Shelfmark is, and who the asks are filed for.
    shelfmark_url: str | None = None
    shelfmark_user_id: int | None = None


@dataclass
class Book:
    title: str
    url: str
    book_id: str
    description: str
    pages: str
    author: str
    isbn: str | None
    read_date: datetime
    rating: str
    year: str

    @cached_property
    def name(self, table=str.maketrans({":": "", "/": "-", "\\": ""})) -> str:
        name = self.title
        for delimiter in (":", "("):
            name = name.split(delimiter, 1)[0]
        return name.translate(table).strip()

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("rating", None)
        return data


def first(sequence):
    for item in sequence:
        return item


def strip_utm(url: str) -> str:
    """Remove utm_medium/utm_source tracking params, keeping the rest of the URL."""
    parts = urlsplit(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query)
        if key not in ("utm_medium", "utm_source")
    ]
    return urlunsplit(parts._replace(query=urlencode(query)))


def json_deserializer(data: dict) -> dict:
    for field in ("read_date",):
        if date := data.get(field):
            data[field] = datetime.fromisoformat(date)
    return data


def get_cache_file(id: str, data_dir: Path) -> Path:
    return data_dir / f"books-{id}-{datetime.now().date().isoformat()}.json"


def get_cached(id: str, data_dir: Path) -> list[Book] | None:
    cache = get_cache_file(id, data_dir)
    if not cache.exists():
        return None

    with cache.open() as stream:
        return [
            Book(**book) for book in json.load(stream, object_hook=json_deserializer)
        ]


def set_cached(id: str, data_dir: Path, books: list[Book]):
    cache = get_cache_file(id, data_dir)
    if cache.exists():
        return

    with cache.open("w") as stream:
        json.dump([asdict(book) for book in books], stream, default=str)


HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
}
# Goodreads retired the shelf RSS feeds on 2026-10-28. What is left without signing in:
# the profile, which counts each shelf, and the shelf widget, at most 100 books a call.
PROFILE_URL = "https://www.goodreads.com/user/show/{user}"
WIDGET_URL = "https://www.goodreads.com/review/custom_widget/{user}.shelf"
AUTOCOMPLETE_URL = "https://www.goodreads.com/book/auto_complete"
# Public, but behind a bot check that challenges a burst: read only for what is missing.
BOOK_URL = "https://www.goodreads.com/book/show/{book_id}"
# After date added both ways, each sort shows another hundred; their union is the shelf.
OTHER_SORTS = [
    (sort, order)
    for sort in ("date_read", "title", "author", "rating", "avg_rating", "date_pub", "num_pages", "position", "random")
    for order in "da"
]


# A slow or busy answer is tried again, after 2, 4 and 8 seconds.
session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=Retry(total=3, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504))))


def get(url: str, **params) -> requests.Response:
    r = session.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r


def shelf_of(url: str) -> tuple[str, str]:
    """The user and shelf of a shelf URL, .../list_rss/<user>?shelf=<shelf> or .../list/<user>?shelf=."""
    parts = urlsplit(url)
    return parts.path.rstrip("/").rsplit("/", 1)[1], dict(parse_qsl(parts.query))["shelf"]


def get_shelf_size(user: str, shelf: str) -> int:
    text = get(PROFILE_URL.format(user=user)).text
    name = re.escape(shelf)
    match = re.search(rf'shelf={name}"[^>]*>\s*{name}&lrm;\s*\((\d+)\)', text)
    if not match:
        raise ShelfError(f"no count of {shelf} on the profile of {user}")
    return int(match[1])


def get_widget(user: str, shelf: str, sort: str, order: str) -> list[dict]:
    """A shelf's books as the widget shows them: title, author, review URL, book ID from the cover."""
    # Goodreads caches a widget by its id whatever the shelf: a fresh id each call.
    r = get(
        WIDGET_URL.format(user=user),
        shelf=shelf, sort=sort, order=order, num_books=100,
        show_author=1, show_cover=1, show_title=1, widget_id=random.randrange(10**9),
    )
    code = re.search(r"var widget_code = '((?:[^'\\]|\\.)*)'", r.content.decode())
    if not code:
        raise ShelfError(f"no widget in the answer for {shelf}")
    html = re.sub(r"\\(.)", lambda m: "\n" if m[1] in "nr" else m[1], code[1])
    soup = BeautifulSoup(html, "html.parser")
    if not soup.find("a", href=re.compile(rf"[?&]shelf={re.escape(shelf)}(&|$)")):
        raise ShelfError(f"the widget served another shelf than {shelf}")
    entries = []
    for item in soup.select("[class^=gr_custom_each_container_]"):
        link = item.select_one("[class^=gr_custom_title_] a")
        cover = re.search(r"/(\d+)\.[^/]*$", item.img["src"]) if item.img else None
        entries.append({
            "title": link.text.strip(),
            "url": strip_utm(link["href"]),
            "author": item.select_one("[class^=gr_custom_author_] a").text.strip(),
            "book_id": cover[1] if cover else None,
        })
    return entries


def search_book_id(title: str, author: str) -> str | None:
    """A book without a cover has no ID in the widget: Goodreads' own search finds it."""
    hits = get(AUTOCOMPLETE_URL, format="json", q=f"{title} {author}").json()
    return first(hit["bookId"] for hit in hits if hit["author"]["name"] == author)


def parse_book_page(html: str, book_id: str) -> dict:
    """ISBN, pages and first publication year of a book page's own data."""
    data = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not data:
        return {}
    state = json.loads(data[1])["props"]["pageProps"]["apolloState"]
    book = first(v for k, v in state.items() if k.startswith("Book:") and v.get("legacyId") == int(book_id))
    if not book:
        return {}
    details = book.get("details") or {}
    work = state.get((book.get("work") or {}).get("__ref"), {})
    published = (work.get("details") or {}).get("publicationTime")
    return {
        "isbn": details.get("isbn") or details.get("isbn13"),
        "pages": details.get("numPages"),
        "year": (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=published)).year if published is not None else None,
    }


def get_book_details(book_id: str | None) -> dict:
    """What the widget lacks, from the book's public page; nothing when it cannot be read."""
    if not book_id:
        return {}
    try:
        r = get(BOOK_URL.format(book_id=book_id))
    except requests.RequestException as error:
        print(f"no details for {book_id}: {error}", file=sys.stderr)
        return {}
    details = parse_book_page(r.text, book_id)
    if not details:
        # A 202 with x-amzn-waf-action: challenge, when Goodreads takes it for a bot.
        print(f"no details for {book_id}: {r.status_code} {r.headers.get('x-amzn-waf-action', '')}", file=sys.stderr)
    return details


def fill(book: Book, details: dict) -> Book:
    """The book with the details it lacks; a value it has is kept."""
    return replace(book, **{key: value for key, value in details.items() if getattr(book, key) is None and value is not None})


def get_shelf(url: str, known: dict[str, Book]) -> list[Book]:
    """Every book of a shelf, newest added first, filled from the books an earlier fetch saw."""
    user, shelf = shelf_of(url)
    size = get_shelf_size(user, shelf)
    newest = get_widget(user, shelf, "date_added", "d")
    oldest = get_widget(user, shelf, "date_added", "a")[::-1]
    found = {entry["url"] for entry in newest + oldest}
    middle = {}
    for sort, order in OTHER_SORTS:
        if len(found) + len(middle) >= size:
            break
        for entry in get_widget(user, shelf, sort, order):
            if entry["url"] not in found:
                middle.setdefault(entry["url"], entry)
    entries = {entry["url"]: entry for entry in newest + list(middle.values()) + oldest}
    # A lost book must not read as one taken off the shelf.
    if len(entries) != size:
        raise ShelfError(f"{shelf}: the widget showed {len(entries)} of {size} books")
    books = [to_book(entry, known.get(entry["url"])) for entry in entries.values()]
    # Newest added first, as the feed had them; a book first seen now goes on top. With no
    # earlier fetch the order is the widget's, and render takes it from the previous list.
    books.sort(key=lambda book: book.read_date, reverse=True)
    return books


def to_book(entry: dict, known: Book | None) -> Book:
    """The widget gives no ISBN, pages, year, description or date: an earlier fetch's,
    else none, the date the one of this first sight."""
    if known:
        return replace(
            known,
            # The widget cuts a trailing (series) or (edition) off the title.
            title=known.title if known.title.startswith(entry["title"]) else entry["title"],
            author=entry["author"],
            book_id=entry["book_id"] or known.book_id,
            read_date=known.read_date or datetime.now().astimezone(),
        )
    return Book(
        title=entry["title"],
        url=entry["url"],
        book_id=entry["book_id"] or search_book_id(entry["title"], entry["author"]),
        description=None,
        pages=None,
        author=entry["author"],
        isbn=None,
        read_date=datetime.now().astimezone(),
        rating=None,
        year=None,
    )


def get_known(id: str, data_dir: Path) -> dict[str, Book]:
    """Every book an earlier fetch of the shelf saw, by its review URL, the newest kept."""
    known = {}
    for cache in sorted(data_dir.glob(f"books-{id}-*.json")):
        with cache.open() as stream:
            for book in json.load(stream, object_hook=json_deserializer):
                known[book["url"]] = Book(**book)
    return known


def get_list(url: str, id: str, data_dir: Path) -> list[Book]:
    if cached := get_cached(id, data_dir):
        return cached
    books = get_shelf(url, get_known(id, data_dir))
    set_cached(id, data_dir, books)
    return books


# Shelfmark's answer once the person has as many waiting asks as they may.
MAX_PENDING_REACHED = "409 max_pending_reached"


class Shelfmark:
    """Files asks in Shelfmark's request queue. Its one endpoint: POST /api/requests."""

    def __init__(self, url: str, api_key: str, user_id: int):
        self.url = url.rstrip("/") + "/api/requests"
        self.api_key = api_key
        self.user_id = user_id

    def ask(self, book: Book) -> tuple[bool, str]:
        """Return whether the ask is in the queue, and Shelfmark's reason when not taken."""
        try:
            r = requests.post(
                self.url,
                json=book_ask(book, self.user_id),
                headers={"X-Api-Key": self.api_key},
                timeout=30,
            )
        except requests.RequestException as error:
            return False, str(error)
        if r.status_code == 201:
            return True, "filed"
        try:
            code = r.json().get("code") or r.json().get("error")
        except ValueError:
            code = r.text[:200]
        # Asked before and still pending: it is in the queue already.
        if code == "duplicate_pending_request":
            return True, code
        return False, f"{r.status_code} {code}"


def book_ask(book: Book, user_id: int) -> dict:
    """A book as Shelfmark's `manual` book: searched by title and author, no metadata lookup."""
    return {
        "book_data": {
            "title": book.title,
            "author": book.author,
            "year": str(book.year) if book.year else None,
            "isbn": book.isbn,
            "content_type": "ebook",
            "provider": "manual",
            "provider_id": book.book_id,
            "source_url": book.url,
        },
        "context": {"content_type": "ebook", "request_level": "book"},
        "on_behalf_of_user_id": user_id,
        "note": "Goodreads",
    }


def get_filed_file(id: str, data_dir: Path) -> Path:
    return data_dir / f"filed-{id}.json"


def get_filed(id: str, data_dir: Path) -> set[str]:
    path = get_filed_file(id, data_dir)
    if not path.exists():
        return set()
    with path.open() as stream:
        return set(json.load(stream))


def set_filed(id: str, data_dir: Path, filed: set[str]):
    path = get_filed_file(id, data_dir)
    partial = path.with_suffix(".tmp")
    with partial.open("w") as stream:
        json.dump(sorted(filed), stream)
    partial.replace(path)


def not_filed(books: list[Book], filed: set[str]) -> list[Book]:
    return [book for book in books if book.book_id not in filed]


def follow(books: list[Book], id: str, data_dir: Path, shelfmark: Shelfmark) -> dict:
    """File every book not filed yet, one ask each, recording each one Shelfmark took.

    At the person's limit of waiting asks it stops: the rest wait for a later run.
    """
    filed = get_filed(id, data_dir)
    counts = {"seen": len(books), "filed": 0, "pending": 0, "refused": 0, "deferred": 0}
    remaining = not_filed(books, filed)
    for index, book in enumerate(remaining):
        if not book.isbn:
            book = fill(book, get_book_details(book.book_id))
        if not book.book_id:
            counts["refused"] += 1
            print(f"refused {book.title!r}: no Goodreads book ID", file=sys.stderr)
            continue
        taken, reason = shelfmark.ask(book)
        if reason == MAX_PENDING_REACHED:
            counts["deferred"] = len(remaining) - index
            break
        if not taken:
            counts["refused"] += 1
            print(f"refused {book.book_id} {book.title!r}: {reason}", file=sys.stderr)
            continue
        counts["filed" if reason == "filed" else "pending"] += 1
        filed.add(book.book_id)
        set_filed(id, data_dir, filed)
    return counts


def write_ratings_list(books: list[Book], path: Path, dir: Path):
    with path.open("w") as stream:
        print(
            f"Leidos {len(books)} libros "
            f"({datetime.now().isoformat(' ', 'minutes')})",
            file=stream,
            end="\n\n",
        )
        for book in books:
            print(
                (
                    f"- [[{book.read_date.date().isoformat()}]]"
                    f" ᐧ [[{dir.name}/{book.name}|{book.name}]]"
                    if book.read_date
                    else ""
                ),
                file=stream,
            )


def make_yaml_parser() -> ruamel.yaml.YAML:
    yaml = ruamel.yaml.YAML(typ="safe")
    yaml.default_flow_style = False
    yaml.explicit_start = True
    yaml.explicit_end = True
    yaml.sort_keys = True
    return yaml


def extract_yaml_doc(path: Path) -> dict:
    yaml = make_yaml_parser()
    data = {}
    with path.open() as stream:
        try:
            data = first(
                yaml.load_all(
                    io.StringIO(
                        "".join(takewhile(lambda line: line != "...\n", stream))
                    )
                )
            )
        except (ValueError, ruamel.yaml.scanner.ScannerError):
            return {}

    if not data or not isinstance(data, dict):
        data = {}

    return data


FILE_TEXT_SEPARATOR_SUFFIX = "----\n"


def extract_file_text(path: Path) -> str:
    separator = FILE_TEXT_SEPARATOR_SUFFIX
    all_text = path.read_text()
    if not separator in all_text:
        return all_text
    with path.open() as stream:
        markers = "\n".join(
            takewhile(lambda line: not line.endswith(separator), stream)
        )
        text = stream.read().strip()
    return text


def save_file(data: dict[str, Any], markers: str, path: Path):
    previous_header = {}
    text = ""
    if path.exists():
        previous_header = extract_yaml_doc(path)
        text = extract_file_text(path)

    data = previous_header | data
    # Loading and dumping again is not lossless: a note nothing changed is left as it is.
    if path.exists() and data == previous_header:
        return

    with path.open("w") as stream:
        yaml = make_yaml_parser()
        yaml.dump(data, stream)
        print("---", file=stream, end="\n\n")
        print(markers, file=stream, end="\n\n")
        print(FILE_TEXT_SEPARATOR_SUFFIX, file=stream)
        print(text, file=stream)


def print_list(url: str, id: str, args):
    print(
        json.dumps(
            [book.to_dict() for book in get_list(url, id, args.data_dir)],
            default=str,
        )
    )


LIST_LINE = re.compile(r"^- \[\[(\d{4}-\d{2}-\d{2})\]\] ᐧ \[\[[^|]*\|(.*)\]\]$", re.MULTILINE)


def get_previous_list(path: Path) -> dict[str, datetime]:
    """The date of each book name in the list a previous render wrote, in its order."""
    if not path.exists():
        return {}
    return {name: datetime.fromisoformat(date) for date, name in LIST_LINE.findall(path.read_text())}


def render_list(url: str, name: str, id: str, args):
    books = get_list(url, id, args.data_dir)
    # The widget has no dates: a book keeps the date and place the list gave it, a new
    # one goes first, dated the run that first saw it.
    previous = get_previous_list(args.listas_dir / name)
    order = {book_name: index for index, book_name in enumerate(previous)}
    books = [replace(book, read_date=previous.get(book.name, book.read_date)) for book in books]
    books.sort(key=lambda book: order.get(book.name, -1))
    write_ratings_list(books, args.listas_dir / name, args.books_dir)
    for book in books:
        path = args.books_dir / (book.name + ".md")
        if path.exists():
            # What the widget lacks stays as the note has it.
            header = extract_yaml_doc(path)
            if not header.get("isbn") or header.get("pages") is None:
                # ponytail: a book Goodreads has no ISBN for is asked again each run.
                book = fill(book, {key: value for key, value in get_book_details(book.book_id).items() if header.get(key) is None})
            book_data = {key: value for key, value in book.to_dict().items() if value is not None}
            if header.get("title", "").startswith(book.title):
                del book_data["title"]
            book_data["author"] = f"[[Autores/{book.author}|{book.author}]]"
            book_data["read_date"] = book.read_date.date().isoformat()
            save_file(book_data, "#libro", path)


def follow_list(url: str, id: str, args):
    config = args.config
    if not config.shelfmark_url or not config.shelfmark_user_id:
        raise FollowConfigError("follow needs shelfmark_url and shelfmark_user_id in the config")
    api_key = os.environ.get("SHELFMARK_API_KEY")
    if not api_key:
        raise FollowConfigError("follow needs SHELFMARK_API_KEY in the environment")

    books = get_list(url, id, args.data_dir)
    shelfmark = Shelfmark(config.shelfmark_url, api_key, config.shelfmark_user_id)
    counts = follow(books, id, args.data_dir, shelfmark)
    print(f"follow {id}: " + " ".join(f"{k}={v}" for k, v in counts.items()))
    return 1 if counts["refused"] else 0


def list_read_command(args):
    print_list(args.config.read_url, "read", args)


def list_want_command(args):
    print_list(args.config.want_url, "want", args)


def render_read_command(args):
    render_list(args.config.read_url, "Libros Leidos.md", "read", args)


def render_want_command(args):
    render_list(args.config.want_url, "Want to Read.md", "want", args)


def follow_want_command(args):
    return follow_list(args.config.want_url, "want", args)


def parse_args(parser):
    args = parser.parse_args()
    args.config = parse_config(args)
    return args


def parse_config(args) -> Config:
    if args.config_json:
        return Config(**json.loads(args.config_json))

    if not args.config_path.exists():
        raise Exception("Missingn configuration at %r", args.config_path)

    with args.config_path.open() as stream:
        return Config(**json.load(stream))


def help(parser: argparse.ArgumentParser, args):
    parser.print_help()


def main():
    common_options = argparse.ArgumentParser(add_help=False)
    common_options.add_argument("--config-json")
    common_options.add_argument(
        "--config",
        type=Path,
        dest="config_path",
        default=Path(__file__).parent / "config.json",
    )
    common_options.add_argument("--data-dir", type=Path, default=Path("data"))
    common_options.add_argument("--listas-dir", type=Path, default=Path("Listas"))
    common_options.add_argument("--books-dir", type=Path, default=Path("Libros"))

    parser = argparse.ArgumentParser("goodreads", parents=[common_options])
    parser.set_defaults(callback=partial(help, parser))
    subparsers = parser.add_subparsers(dest="commands")

    list_parser = subparsers.add_parser("list", parents=[common_options])
    list_parser.set_defaults(callback=partial(help, list_parser))
    list_subparsers = list_parser.add_subparsers(title="subcommands")

    list_read_parser = list_subparsers.add_parser("read", parents=[common_options])
    list_read_parser.set_defaults(callback=list_read_command)

    list_want_parser = list_subparsers.add_parser("want", parents=[common_options])
    list_want_parser.set_defaults(callback=list_want_command)

    render_parser = subparsers.add_parser("render", parents=[common_options])
    render_parser.set_defaults(callback=partial(help, render_parser))
    render_subparsers = render_parser.add_subparsers(title="subcommands")

    render_read_parser = render_subparsers.add_parser("read", parents=[common_options])
    render_read_parser.set_defaults(callback=render_read_command)

    render_want_parser = render_subparsers.add_parser("want", parents=[common_options])
    render_want_parser.set_defaults(callback=render_want_command)

    follow_parser = subparsers.add_parser("follow", parents=[common_options])
    follow_parser.set_defaults(callback=partial(help, follow_parser))
    follow_subparsers = follow_parser.add_subparsers(title="subcommands")

    follow_want_parser = follow_subparsers.add_parser("want", parents=[common_options])
    follow_want_parser.set_defaults(callback=follow_want_command)

    args = parse_args(parser)
    result = args.callback(args)
    sys.exit(0 if not result else result)


if __name__ == "__main__":
    main()
