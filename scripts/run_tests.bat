@echo off
REM Run tests with coverage (Windows)

echo Running Prism test suite...

pytest tests/ --cov=apps --cov-report=term-missing --cov-report=html:coverage_html -v

echo.
echo Tests complete! Coverage report available at coverage_html\index.html
