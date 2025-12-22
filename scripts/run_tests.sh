#!/bin/bash
# Run tests with coverage

set -e

echo "Running Prism test suite..."

# Run pytest with coverage
pytest tests/ \
    --cov=apps \
    --cov-report=term-missing \
    --cov-report=html:coverage_html \
    -v

echo ""
echo "Tests complete! Coverage report available at coverage_html/index.html"
