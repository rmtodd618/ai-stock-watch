#!/usr/bin/env bash
# Build a clean Lambda deployment artifact in ./build — no Docker required.
#
# Cross-installs Linux x86_64 wheels for the runtime deps (pandas/numpy ship
# platform-specific binaries that must match Lambda's OS, not your Mac), then
# copies in only src/ and the config. SAM/CloudFormation packages ./build as-is.
set -euo pipefail

cd "$(dirname "$0")/.."

PY_VERSION="3.12"
PLATFORM="manylinux2014_x86_64"

echo "Cleaning ./build ..."
rm -rf build
mkdir -p build

echo "Installing Linux x86_64 deps for Python ${PY_VERSION} ..."
python3 -m pip install \
  --target build \
  --platform "${PLATFORM}" \
  --implementation cp \
  --python-version "${PY_VERSION}" \
  --only-binary=:all: \
  --upgrade \
  -r requirements-lambda.txt

echo "Copying application source ..."
cp -r src build/src
cp config.example.yaml build/config.example.yaml

echo "Trimming artifact (test suites, caches) ..."
find build -type d -name "__pycache__" -prune -exec rm -rf {} + 2>/dev/null || true
find build -type d -name "tests" -prune -exec rm -rf {} + 2>/dev/null || true
find build -name "*.pyc" -delete 2>/dev/null || true
# NOT *.dist-info. Packages that read their own version through
# importlib.metadata need that directory present at import time. Deleting it
# was harmless until the anthropic SDK pulled in httpx2, whose __init__ calls
# version("httpx2") — the 2026-11-12 run died on PackageNotFoundError before
# it could score anything. The metadata is a few MB against a 250MB limit.

echo "Build complete: ./build ($(du -sh build | cut -f1))"
