.PHONY: help install test lint run-viewer sam-build sam-deploy clean

help:
	@echo "make install     - install dev deps (root + generator)"
	@echo "make test        - run pytest"
	@echo "make lint        - run ruff"
	@echo "make run-viewer  - run streamlit locally"
	@echo "make sam-build   - sam build"
	@echo "make sam-deploy  - sam deploy"

install:
	python3 -m pip install -U pip
	python3 -m pip install -r requirements.txt
	python3 -m pip install -r src/requirements.txt
	python3 -m pip install pytest pytest-mock moto ruff

test:
	python3 -m pytest

lint:
	python3 -m ruff check .

run-viewer:
	streamlit run app.py

sam-build:
	sam build --template template.yaml

sam-deploy:
	sam deploy --no-confirm-changeset

clean:
	rm -rf .pytest_cache .aws-sam build dist *.egg-info
