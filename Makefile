.PHONY: install dev docs test lint fmt clean build publish publish-test

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	pytest -v

lint:
	ruff check src/ tests/

fmt:
	ruff format src/ tests/
	ruff check --fix src/ tests/

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +

docs:
	mkdocs serve

docs-build:
	mkdocs build

build: clean
	python -m build

publish-test: build
	twine upload --repository testpypi dist/*

publish: build
	twine upload dist/*

embeddings-up:
	docker compose up -d embeddings

embeddings-down:
	docker compose down embeddings
