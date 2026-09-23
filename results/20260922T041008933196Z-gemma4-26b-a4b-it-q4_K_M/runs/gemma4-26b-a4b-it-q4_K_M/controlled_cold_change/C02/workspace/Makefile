.PHONY: migrate test lint typecheck
migrate:
	alembic upgrade head
test:
	pytest -q
lint:
	ruff check stockflow tests
typecheck:
	mypy stockflow

