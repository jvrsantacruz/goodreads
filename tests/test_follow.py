from datetime import UTC, datetime

import pytest
from hamcrest import assert_that, contains_inanyorder, empty, equal_to, has_entries

import goodreads
from goodreads import Book, Config, book_ask, follow, get_filed, set_filed


def make_book(book_id: str, title: str = "Dune") -> Book:
    return Book(
        title=title,
        url=f"https://www.goodreads.com/book/show/{book_id}",
        book_id=book_id,
        description="",
        pages=None,
        author="Frank Herbert",
        isbn="0441013597",
        read_date=datetime(2026, 10, 5, tzinfo=UTC),
        rating=None,
        year=1965,
    )


class FakeShelfmark:
    def __init__(self, answers: dict[str, tuple[bool, str]] | None = None):
        self.answers = answers or {}
        self.asked = []

    def ask(self, book: Book) -> tuple[bool, str]:
        self.asked.append(book.book_id)
        return self.answers.get(book.book_id, (True, "filed"))


def test_config_takes_the_actions_keys_alone():
    config = Config(read_url="r", want_url="w")

    assert_that(config.shelfmark_url, equal_to(None))


def test_an_ask_is_a_manual_ebook_for_the_person():
    ask = book_ask(make_book("1"), user_id=2)

    assert_that(ask, has_entries(on_behalf_of_user_id=2))
    assert_that(
        ask["book_data"],
        has_entries(title="Dune", author="Frank Herbert", provider="manual", provider_id="1"),
    )


def test_first_run_files_the_whole_shelf(tmp_path):
    shelfmark = FakeShelfmark()

    counts = follow([make_book("1"), make_book("2")], "want", tmp_path, shelfmark)

    assert_that(counts, has_entries(seen=2, filed=2, refused=0))
    assert_that(get_filed("want", tmp_path), contains_inanyorder("1", "2"))


def test_a_filed_book_is_not_asked_again(tmp_path):
    set_filed("want", tmp_path, {"1"})
    shelfmark = FakeShelfmark()

    follow([make_book("1"), make_book("2")], "want", tmp_path, shelfmark)

    assert_that(shelfmark.asked, equal_to(["2"]))


def test_a_refused_ask_is_not_recorded_and_stops_no_other(tmp_path):
    shelfmark = FakeShelfmark({"1": (False, "409 max_pending")})

    counts = follow([make_book("1"), make_book("2")], "want", tmp_path, shelfmark)

    assert_that(counts, has_entries(filed=1, refused=1))
    assert_that(get_filed("want", tmp_path), equal_to({"2"}))


def test_an_ask_already_pending_is_recorded(tmp_path):
    shelfmark = FakeShelfmark({"1": (True, "duplicate_pending_request")})

    counts = follow([make_book("1")], "want", tmp_path, shelfmark)

    assert_that(counts, has_entries(filed=0, pending=1))
    assert_that(get_filed("want", tmp_path), equal_to({"1"}))


def test_an_empty_shelf_files_nothing(tmp_path):
    counts = follow([], "want", tmp_path, FakeShelfmark())

    assert_that(counts, has_entries(seen=0, filed=0))
    assert_that(get_filed("want", tmp_path), empty())


def test_a_failed_page_is_not_the_end_of_the_shelf(monkeypatch):
    class Failed:
        text = ""

        def raise_for_status(self):
            raise goodreads.requests.HTTPError("503")

    monkeypatch.setattr(goodreads.requests, "get", lambda *_, **__: Failed())

    with pytest.raises(goodreads.requests.HTTPError):
        goodreads.get_pages("https://www.goodreads.com/review/list_rss/1")
