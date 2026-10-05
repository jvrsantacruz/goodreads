.DEFAULT_GOAL := help
.PHONY: help lint test

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
