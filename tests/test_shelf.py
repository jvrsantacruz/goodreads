from datetime import UTC, datetime

import pytest
from hamcrest import assert_that, contains_exactly, equal_to

import goodreads
from goodreads import (
    Book,
    ShelfError,
    get_previous_list,
    get_widget,
    to_book,
)

# A widget answer as Goodreads serves it: HTML inside a JavaScript string.
WIDGET = r"""  var widget_code = '  <div class=\"gr_custom_container_7\">\n    <h2 class=\"gr_custom_header_7\">\n    <a href=\"https://www.goodreads.com/review/list/1-x?shelf=to-read&amp;utm_medium=api\">shelf<\/a>\n    <\/h2>\n      <div class=\"gr_custom_each_container_7\">\n          <div class=\"gr_custom_book_container_7\">\n            <a href=\"https://www.goodreads.com/review/show/11?utm_medium=api&amp;utm_source=custom_widget\"><img alt=\"x\" src=\"https://i.gr-assets.com/images/S/compressed.photo.goodreads.com/books/1612784168l/1136437._SY75_.jpg\" /><\/a>\n          <\/div>\n          <div class=\"gr_custom_title_7\">\n            <a href=\"https://www.goodreads.com/review/show/11?utm_medium=api&amp;utm_source=custom_widget\">Don\'t Panic<\/a>\n          <\/div>\n          <div class=\"gr_custom_author_7\">\n            by <a href=\"https://www.goodreads.com/author/show/2.B\">Belén Gopegui<\/a>\n          <\/div>\n      <\/div>\n      <div class=\"gr_custom_each_container_7\">\n          <div class=\"gr_custom_book_container_7\">\n            <a href=\"https://www.goodreads.com/review/show/12\"><img src=\"https://s.gr-assets.com/assets/nophoto/book/50x75-1b9.png\" /><\/a>\n          <\/div>\n          <div class=\"gr_custom_title_7\"><a href=\"https://www.goodreads.com/review/show/12\">El deseo<\/a><\/div>\n          <div class=\"gr_custom_author_7\">by <a href=\"#\">A<\/a><\/div>\n      <\/div>\n  <\/div>\n'
  var widget_div = document.getElementById('gr_custom_widget_7')"""


class Answer:
    content = WIDGET.encode()


@pytest.fixture
def widget(monkeypatch):
    monkeypatch.setattr(goodreads, "get", lambda url, **params: Answer())


@pytest.mark.usefixtures("widget")
def test_the_widget_gives_title_author_review_and_cover_book_id():
    entries = get_widget("1", "to-read", "date_added", "d")

    assert_that(
        entries,
        contains_exactly(
            equal_to({"title": "Don't Panic", "url": "https://www.goodreads.com/review/show/11", "author": "Belén Gopegui", "book_id": "1136437"}),
            equal_to({"title": "El deseo", "url": "https://www.goodreads.com/review/show/12", "author": "A", "book_id": None}),
        ),
    )


@pytest.mark.usefixtures("widget")
def test_a_widget_of_another_shelf_fails():
    with pytest.raises(ShelfError):
        get_widget("1", "read", "date_added", "d")


def test_a_known_book_keeps_its_full_title_and_fields():
    known = Book("Manía (Spanish Edition)", "u", "9", "d", 300, "L", "1", datetime(2020, 1, 1, tzinfo=UTC), 4.0, 2000)

    book = to_book({"title": "Manía", "url": "u", "author": "L", "book_id": "9"}, known)

    assert_that(book, equal_to(known))


def test_the_previous_list_gives_each_name_its_date_in_order(tmp_path):
    path = tmp_path / "list.md"
    path.write_text("Leidos 2 libros (x)\n\n- [[2026-09-21]] ᐧ [[libros/B|B]]\n- [[2026-08-30]] ᐧ [[libros/A|A]]\n")

    assert_that(list(get_previous_list(path).items()), contains_exactly(("B", datetime(2026, 9, 21)), ("A", datetime(2026, 8, 30))))
