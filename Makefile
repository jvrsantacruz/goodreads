.DEFAULT_GOAL := help
.PHONY: help lint test e2e

UV_RUN := uv run --no-project --with-requirements requirements.txt

## help   this list
help:
	@sed -n 's/^## //p' $(firstword $(MAKEFILE_LIST))

## lint   ruff's default rules and vulture
lint:
	uvx ruff check goodreads.py tests
	uvx vulture goodreads.py tests --min-confidence 80

## test   the pytest suite
test:
	$(UV_RUN) --with pytest --with pyhamcrest --with pytest-randomly python -m pytest -q tests

## e2e    render live over the me repo's lists and notes; nothing previous may change
e2e:
	@dir=$${ME_REPO:-$$(mktemp -d)}; \
	if [ -z "$$ME_REPO" ]; then git clone -q --depth 1 --filter=blob:none --sparse git@github.com:jvrsantacruz/me.git $$dir && git -C $$dir sparse-checkout set Listas Libros; fi; \
	ME_REPO=$$dir $(UV_RUN) --with pytest python -m pytest -q tests/e2e; status=$$?; \
	if [ -z "$$ME_REPO" ]; then rm -rf "$$dir"; fi; exit $$status
