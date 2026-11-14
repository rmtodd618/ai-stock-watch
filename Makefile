.PHONY: install test run dashboard build deploy clean

install:
	pip install -r requirements.txt -r requirements-dev.txt

test:
	pytest

run:
	python -m src.handler

# Rebuild the live-record page from the archived snapshots and open it.
# No hosting, no cost: it is regenerated each time, so it is never stale.
dashboard:
	python scripts/publish_dashboard.py --open

build:
	bash scripts/build-lambda.sh

deploy: build
	sam deploy -t infra/template.yaml

clean:
	rm -rf .aws-sam build .pytest_cache report.html report.txt dashboard.html
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
