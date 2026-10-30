from hamcrest import assert_that, ends_with, equal_to, has_entries

import goodreads
from goodreads import save_file


def test_a_note_nothing_changed_is_left_as_it_is(tmp_path):
    path = tmp_path / "note.md"
    text = "---\ndescription: two  spaces, wrapped by another writer \n  long ago\nread_date: '2020-01-01'\n---\n\n#libro\n\n----\n\nmine\n"
    path.write_text(text)

    save_file({"read_date": "2020-01-01"}, "#libro", path)

    assert_that(path.read_text(), equal_to(text))


def test_a_changed_note_keeps_its_multiline_values_and_text(tmp_path):
    path = tmp_path / "note.md"
    path.write_text("---\ndescription: a long line\n  folded\nread_date: '2020-01-01'\n---\n\n#libro\n\n----\n\nmine\n")

    save_file({"read_date": "2020-01-02"}, "#libro", path)

    assert_that(goodreads.extract_yaml_doc(path), has_entries(description="a long line folded", read_date="2020-01-02"))
    assert_that(path.read_text(), ends_with("mine\n"))
