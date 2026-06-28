# 0001 — Plan template

**Status:** accepted **·** **Owner:** jvr **·** **Updated:** 2026-06-28

## Why this exists

Plans in `plans/` describe features that are not yet built. Each plan is one Markdown file under **300 words** that a future contributor (human or LLM) can read end-to-end and turn into a PR. Plans pin down the *what* and *why*; the *how* is left to the implementer with enough scaffolding that two implementers wouldn't drift apart. Think ADR-lite. This repo is a single-file tool (`goodreads.py`), so most plans land as a new CLI verb, a new field, or a render-behavior change.

## Functional requirements

- Filename: `NNNN-kebab-slug.md`, where `NNNN` is zero-padded monotonic.
- One feature per file. Grow scope → split.
- The plan must answer: business problem; observable success; expected input/output.
- Use tables, code blocks, mock JSON/XML, ASCII diagrams freely — they don't count toward the word budget.

## Non-functional requirements

- **Body ≤ 300 words.** Tables and fenced code blocks excluded from the count.
- Plain Markdown only. No external image assets.
- Cross-link with `[[NNNN-slug]]`. Status: `draft` / `accepted` / `shipped` / `dropped`.
- A `dropped` plan keeps the file and adds a one-line pointer to whichever plan supersedes it.
- Respect existing constraints: single-file app, daily JSON cache under `data/`, render only touches `.md` files that already exist.

## Required sections

| Section | Purpose |
|---|---|
| Why this exists | Business problem, 2–4 sentences |
| Functional reqs | Must-haves, bullet list |
| Non-functional reqs | Constraints (cache, offline, Obsidian links, tech) |
| Implementation hint | Concrete sketch: new CLI verb, `Book` field, render rule, config keys, function signatures |
| Examples / refs | Sample I/O, related plans, links — optional |

## Implementation hint

Copy this file, bump the number, rewrite the body. Plans are reviewed on PRs that touch only `plans/`. Implementation PRs reference the plan in their description (`Implements [[0042-foo]]`). When the feature ships, flip the plan's status to `shipped` in the same PR. Keep new code inside `goodreads.py` unless a plan explicitly argues for splitting the module.

## References

- [ADR](https://adr.github.io/) — same idea, more formal.
- `CLAUDE.md` — architecture and data-flow this repo's plans build on.
- [[0002-…]] — next plan goes here.
