.PHONY: migrate migrate-expand migrate-contract test lint typecheck

migrate-expand:
	alembic upgrade 0002_expand_orders_tax

migrate-contract:
	alembic upgrade 0003_contract_orders_tax

migrate:
	alembic upgrade head

test:
	pytest -q

lint:
	ruff check stockflow tests

typecheck:
	mypy stockflow