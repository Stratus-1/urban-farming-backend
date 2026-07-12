.PHONY: install dev lint format test run db-bootstrap

# Replay the schema (compatibility shim + all migrations) into the local compose postgres.
db-bootstrap:
	DATABASE_URL_PSQL=postgresql://urban_farming:local-development-only@127.0.0.1:5432/urban_farming \
		scripts/bootstrap_cloud_sql.sh

install:
	uv sync --extra dev

dev:
	uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest --cov=app --cov-report=term-missing

run:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

