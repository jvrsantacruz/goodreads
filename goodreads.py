#!/usr/bin/env python3
"""

See: https://github.com/maria-antoniak/goodreads-scraper/blob/master/get_books.py
"""

import argparse
import io
import json
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from functools import cached_property, partial
from itertools import count, takewhile
from pathlib import Path
from typing import Any, Iterable, Union
from xml.dom.minidom import Document, Element, Text
from xml.dom.pulldom import parse

import requests
import ruamel.yaml
from bs4 import BeautifulSoup


@dataclass
class Event:
    status: str
    node: Union[Document, Element, Text]

    @cached_property
    def name(self) -> str:
        return self.node.nodeName

    @cached_property
    def value(self) -> str:
        return self.node.nodeValue

    @cached_property
    def is_text(self) -> bool:
        return self.status == "CHARACTERS"

    @cached_property
    def is_start(self) -> bool:
        return self.status == "START_ELEMENT"

    @cached_property
    def is_end(self) -> bool:
        return self.status == "END_ELEMENT"


@dataclass
class Config:
    read_url: str
    want_url: str


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

    @classmethod
    def from_goodreads(cls, entry: dict[str, str]):
        return cls(
            **{
                "title": entry["title"],
                "url": entry["link"],
                "book_id": entry["book_id"],
                "pages": to_int(entry["num_pages"]),
                "author": entry["author_name"],
                "isbn": entry["isbn"].strip() if entry["isbn"].strip() else None,
                "read_date": to_date(entry["pubDate"])
                or to_date(entry["user_date_added"])
                or to_date(entry["user_date_created"]),
                "rating": to_float(entry["average_rating"]),
                "year": to_int(entry["book_published"]),
                "description": entry["book_description"],
            }
        )

    @cached_property
    def name(self, table=str.maketrans({":": "", "/": "-", "\\": ""})) -> str:
        name = self.title
        for delimiter in (":", "("):
            name = name.split(delimiter, 1)[0]
        return name.translate(table).strip()


def first(sequence):
    for item in sequence:
        return item


def to_date(text: str) -> datetime | None:
    """Fri, 30 Nov 2018 07:08:00 -0800"""
    try:
        return datetime.strptime(text, "%a, %d %b %Y %H:%M:%S %z")
    except ValueError:
        return None


def to_int(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def to_float(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def parse_item(events: Iterable[Event]) -> dict[str, str]:
    first(e for e in events if e.name == "item" and e.is_start)
    current_name = None
    item = defaultdict(str)
    for event in takewhile(lambda e: not (e.name == "item"), events):
        if event.is_start:
            current_name = event.name
        elif event.is_text and current_name:
            item[current_name] += event.value
        elif event.is_end:
            item[current_name] = BeautifulSoup(
                item[current_name].strip(), "html.parser"
            ).text
            current_name = None

    return item


def parse_list(text: str):
    events = (Event(status, node) for status, node in parse(io.StringIO(text)))
    for event in takewhile(lambda e: not (e.is_end and e.name == "channel"), events):
        item = parse_item(events)
        if not item.get("book_id"):
            continue
        yield Book.from_goodreads(item)


def json_deserializer(data: dict) -> dict:
    for field in ("read_date",):
        if date := data.get(field):
            data[field] = datetime.fromisoformat(date)
    return data


def get_cache_file(id: str, data_dir: Path) -> Path:
    return Path(f"data/books-{id}-{datetime.now().date().isoformat()}.json")


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


def get_page(url: str, page: int) -> list[Book]:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36"
    }
    r = requests.get(url, params=dict(page=page), headers=headers)
    return list(parse_list(r.text))


def get_pages(url: str) -> list[Book]:
    all_books = []
    for page in count(1):
        books = get_page(url, page=page)
        if not books:
            break
        all_books += books
    return all_books


def get_list(url: str, id: str, data_dir: Path) -> list[Book]:
    if cached := get_cached(id, data_dir):
        return cached
    books = get_pages(url)
    set_cached(id, data_dir, books)
    return books


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
                f"- [[{book.read_date.date().isoformat()}]]"
                f" ᐧ [[{dir.name}/{book.name}|{book.name}]]"
                if book.read_date
                else "",
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
                        "\n".join(takewhile(lambda line: line != "...\n", stream))
                    )
                )
            )
        except (ValueError, ruamel.yaml.scanner.ScannerError):
            return {}

    if not data or not isinstance(data, dict):
        data = {}

    return data


def extract_file_text(path: Path) -> str:
    separator = "----\n"
    all_text = path.read_text()
    if not separator in all_text:
        return all_text
    with path.open() as stream:
        markers = "\n".join(takewhile(lambda line: line != separator, stream))
        text = stream.read().strip()
    return text


def save_file(data: dict[str, Any], markers: str, path: Path):
    previous_header = {}
    text = ""
    if path.exists():
        previous_header = extract_yaml_doc(path)
        text = extract_file_text(path)

    data = previous_header | data

    with path.open("w") as stream:
        yaml = make_yaml_parser()
        yaml.dump(data, stream)
        print("---", file=stream, end="\n\n")
        print(markers, file=stream, end="\n\n")
        print(f"----\n", file=stream)
        print(text, file=stream)


def print_list(url: str, id: str, args):
    print(
        json.dumps(
            [asdict(book) for book in get_list(url, id, args.data_dir)],
            default=str,
        )
    )


def render_list(url: str, name: str, id: str, args):
    books = get_list(url, id, args.data_dir)
    write_ratings_list(books, args.listas_dir / name, args.books_dir)
    for book in books:
        path = args.books_dir / (book.name + ".md")
        if path.exists():
            book_data = asdict(book)
            book_data["author"] = f"[[Autores/{book.author}|{book.author}]]"
            book_data["read_date"] = book.read_date.date().isoformat()
            save_file(book_data, "#libro", path)


def list_read_command(args):
    print_list(args.config.read_url, "read", args)


def list_want_command(args):
    print_list(args.config.read_url, "want", args)


def render_read_command(args):
    render_list(args.config.read_url, "Libros Leidos.md", "read", args)


def render_want_command(args):
    render_list(args.config.want_url, "Want to Read.md", "want", args)


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
    common_options.add_argument('--config-json')
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

    args = parse_args(parser)
    result = args.callback(args)
    sys.exit(0 if not result else result)


if __name__ == "__main__":
    main()
