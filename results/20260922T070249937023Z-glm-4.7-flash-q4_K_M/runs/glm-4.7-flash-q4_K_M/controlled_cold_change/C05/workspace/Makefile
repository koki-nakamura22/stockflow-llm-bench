.PHONY: migrate test lint typecheck migrate-expand migrate-contract
migrate:
	alembic upgrade head
migrate-expand:
	alembic upgrade 0002_expand_order_columns
migrate-contract:
	alembic upgrade 0003_contract_order_columns
test:
	pytest -q
lint:
	ruff check stockflow tests
typecheck:
	mypy stockflow

