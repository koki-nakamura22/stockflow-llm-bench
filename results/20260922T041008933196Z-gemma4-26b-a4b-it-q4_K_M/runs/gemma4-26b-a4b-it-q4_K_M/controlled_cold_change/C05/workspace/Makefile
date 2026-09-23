.PHONY: migrate test lint typecheck
migrate:
	alembic upgrade head
migrate-expand:
	alembic upgrade 0002_expand
migrate-contract:
	alembic upgrade 0003_contract
test:
	pytest -q
lint:
	ruff check stockflow tests
typecheck:
	mypy stockflow

