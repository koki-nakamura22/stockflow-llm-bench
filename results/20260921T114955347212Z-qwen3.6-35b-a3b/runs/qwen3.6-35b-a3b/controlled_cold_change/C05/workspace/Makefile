.PHONY: migrate migrate-expand migrate-contract test lint typecheck
migrate:
	alembic upgrade head
migrate-expand:
	alembic upgrade 0002_expand_tax_columns
migrate-contract:
	alembic upgrade 0003_contract_tax_columns
test:
	pytest -q
lint:
	ruff check stockflow tests
typecheck:
	mypy stockflow

