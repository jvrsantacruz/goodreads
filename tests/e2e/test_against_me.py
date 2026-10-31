"""Renders both shelves from Goodreads, live, over a copy of the `me` repo's lists and notes,
and compares the two side by side: what the previous run wrote must still be there.

    make e2e                     # clones the me repo, sparse, into a temporary directory
    ME_REPO=<checkout> make e2e  # or uses one

The shelves are the config's, `GOODREADS_CONFIG` as the Action's secret, else `config.json`.
"""

import difflib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
ME_REPO = os.environ.get("ME_REPO")
LISTS = {"read": "Libros Leidos.md", "want": "Want to Read.md"}

pytestmark = pytest.mark.skipif(not ME_REPO, reason="needs ME_REPO, a checkout of the me repo")


def config() -> str:
    if text := os.environ.get("GOODREADS_CONFIG"):
        return text
    return (ROOT / "config.json").read_text()


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """The previous lists and notes, and the same after a render of both shelves."""
    before = Path(ME_REPO)
    after = tmp_path_factory.mktemp("me")
    # Named as the Action mounts them: the list links carry the notes' directory name.
    shutil.copytree(before / "Listas", after / "listas")
    shutil.copytree(before / "Libros", after / "libros")
    (after / "data").mkdir()
    for shelf in LISTS:
        subprocess.run(
            [sys.executable, str(ROOT / "goodreads.py"), "render", shelf,
             "--config-json", json.dumps(json.loads(config())),
             "--data-dir", str(after / "data"),
             "--listas-dir", str(after / "listas"), "--books-dir", str(after / "libros")],
            check=True,
        )
    return before, after


def side_by_side(old: list[str], new: list[str]) -> str:
    rows = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        for k in range(max(i2 - i1, j2 - j1)):
            left = old[i1 + k] if i1 + k < i2 else ""
            right = new[j1 + k] if j1 + k < j2 else ""
            rows.append(f"{left:<90.90} | {right}")
    return "\n".join([f"{'previous':<90} | new", *rows])


@pytest.mark.parametrize("shelf", LISTS)
def test_a_list_loses_no_entry_and_adds_only_on_top(run, shelf):
    before, after = run
    # The first line is the count and the time of the run.
    old = (before / "Listas" / LISTS[shelf]).read_text().splitlines()[1:]
    new = (after / "listas" / LISTS[shelf]).read_text().splitlines()[1:]

    added = len(new) - len(old)
    assert added >= 0 and new[added:] == old, side_by_side(old, new)


def test_no_note_changes(run):
    before, after = run
    changed = {
        note.name: side_by_side(note.read_text().splitlines(), (after / "libros" / note.name).read_text().splitlines())
        for note in (before / "Libros").glob("*.md")
        if note.read_bytes() != (after / "libros" / note.name).read_bytes()
    }

    assert not changed, "\n\n".join(f"{name}\n{diff}" for name, diff in changed.items())
