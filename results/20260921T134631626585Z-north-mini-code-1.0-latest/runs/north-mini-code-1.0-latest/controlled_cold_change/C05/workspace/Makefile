.PHONY: migrate migrate-expand migrate-contract test lint typecheck
migrate:
	alembic upgrade head
migrate-expand:
	alembic upgrade 0002
migrate-contract:
	alembic upgrade 0003
test:
	pytest -q
lint:
	ruff check stockflow tests
typecheck:
	mypy stockflow

