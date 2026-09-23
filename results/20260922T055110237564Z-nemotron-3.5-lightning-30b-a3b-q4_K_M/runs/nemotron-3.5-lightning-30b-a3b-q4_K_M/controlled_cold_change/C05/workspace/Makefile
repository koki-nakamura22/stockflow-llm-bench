.PHONY: migrate test lint typecheck migrate-expand migrate-contract
migrate:
	alembic upgrade head
test:
	pytest -q
lint:
	ruff check stockflow tests
typecheck:
	mypy stockflow
migrate-expand:
	alembic upgrade 0002_expand
migrate-contract:
	alembic upgrade 0003_contract

