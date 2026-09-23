.PHONY: migrate test lint typecheck migrate-expand migrate-contract
migrate:
	alembic upgrade head
migrate-expand:
	alembic upgrade 0002_expand_tax_columns
migrate-contract:
	alembic upgrade 0003_contract_remove_total
test:
	pytest -q
lint:
	ruff check stockflow tests
typecheck:
	mypy stockflow
