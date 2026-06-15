.PHONY: install test run build deploy clean

install:
	pip install -r requirements.txt -r requirements-dev.txt

test:
	pytest

run:
	python -m src.handler

build:
	sam build --use-container -t infra/template.yaml

deploy: build
	sam deploy --guided -t infra/template.yaml

clean:
	rm -rf .aws-sam .pytest_cache report.html report.txt
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# Invoked by `sam build` (BuildMethod: makefile). Populates ARTIFACTS_DIR with
# only the runtime deps + source — no .venv, .git, or tests. Run via
# `sam build --use-container` so wheels are built for Lambda's Linux x86_64.
build-StockWatchFunction:
	pip install -r requirements-lambda.txt -t "$(ARTIFACTS_DIR)"
	cp -r src "$(ARTIFACTS_DIR)/src"
	cp config.example.yaml "$(ARTIFACTS_DIR)/config.example.yaml"
