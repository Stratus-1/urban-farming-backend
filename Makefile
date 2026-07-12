.PHONY: install dev lint format test run

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

