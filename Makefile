.PHONY: install test run build deploy clean

install:
	pip install -r requirements.txt -r requirements-dev.txt

test:
	pytest

run:
	python -m src.handler

build:
	sam build -t infra/template.yaml

deploy: build
	sam deploy --guided -t infra/template.yaml

clean:
	rm -rf .aws-sam .pytest_cache report.html report.txt
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
