# 0003 — Follow the want shelf into Shelfmark

**Status:** done **·** **Owner:** jvr **·** **Updated:** 2026-10-05

## Why it exists

A book on the want shelf is asked for again in Shelfmark, the lab's book request queue, by hand.
The spec and its reasons live in the tech vault: `goodreads-intent` and the ADR
`2026-10-05-goodreads-shelves-become-shelfmark-asks`.

## Functional requirements

- `follow want` files each book of the want shelf not filed yet as one Shelfmark ask.
- A book is known by its Goodreads book ID; the filed IDs live in `data/filed-want.json`.
- An ID is recorded only after Shelfmark took the ask; a refused one is retried next run.
- A failed feed page files nothing.
- `list` and `render`, their config keys and the image stay as they are.
