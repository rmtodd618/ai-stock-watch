# Everything runs out of a project-local virtualenv, created on first use.
# The repo has no `python` on PATH (only `python3`) and no interpreter with the
# dependencies installed, so targets that assumed either one could not work.
VENV    := .venv
PY      := $(VENV)/bin/python
PIP     := $(VENV)/bin/pip
STACK   := ai-stock-watch

# Resolved from CloudFormation so nothing has to be configured by hand. Override
# with `make dashboard BUCKET=...` or by exporting REPORT_BUCKET.
BUCKET ?= $(or $(REPORT_BUCKET),$(shell aws cloudformation describe-stacks \
            --stack-name $(STACK) \
            --query 'Stacks[0].Outputs[?OutputKey==`ReportBucketName`].OutputValue' \
            --output text 2>/dev/null))

.PHONY: venv install test run dashboard build deploy clean

$(PY):
	@echo "Creating $(VENV) ..."
	python3 -m venv $(VENV)
	@$(PIP) install -q --upgrade pip
	@$(PIP) install -q -r requirements.txt

venv: $(PY)

install: $(PY)
	@$(PIP) install -q -r requirements.txt -r requirements-dev.txt

test: install
	$(VENV)/bin/pytest

run: $(PY)
	$(PY) -m src.handler

# Rebuild the live-record page from the archived snapshots and open it.
# No hosting and no cost: regenerated on every run, so it cannot go stale.
dashboard: $(PY)
	@test -n "$(BUCKET)" || { \
	  echo "No bucket found. Set REPORT_BUCKET or pass BUCKET=<name>."; exit 1; }
	REPORT_BUCKET=$(BUCKET) $(PY) scripts/publish_dashboard.py --bucket $(BUCKET) --open

build:
	bash scripts/build-lambda.sh

deploy: build
	sam deploy -t infra/template.yaml

clean:
	rm -rf .aws-sam build .pytest_cache report.html report.txt dashboard.html
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
