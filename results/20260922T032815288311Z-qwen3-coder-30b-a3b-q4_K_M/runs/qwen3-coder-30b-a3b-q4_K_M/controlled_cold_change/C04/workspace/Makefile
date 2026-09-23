.PHONY: migrate test lint typecheck run-worker
migrate:
	alembic upgrade head
test:
	pytest -q
lint:
	ruff check stockflow tests
typecheck:
	mypy stockflow
run-worker:
	python -m stockflow.outbox_worker --once

