# Developer shortcuts. Everything here runs without root or WiFi hardware.
#
#   make dev        install the package (editable) + dev tools into the active env
#   make check      lint + type check + tests with coverage (what CI runs)
#
# Tools run as `$(PYTHON) -m <tool>`, so they come from the same environment
# as the code under test (e.g. an activated .venv).
PYTHON ?= python3

.PHONY: dev test coverage lint typecheck lint-ci fmt check gui gui-smoke site clean

# uv-managed environments have no pip; use uv when it's available.
dev:
	@if command -v uv >/dev/null 2>&1; then \
		uv sync; \
	else \
		$(PYTHON) -m pip install --upgrade "pip>=25.1" && $(PYTHON) -m pip install -e . --group dev; \
	fi

test:
	$(PYTHON) -m unittest discover -s tests -t .

coverage: _require-dev
	$(PYTHON) -m coverage run -m unittest discover -s tests -t .
	$(PYTHON) -m coverage report

lint: _require-dev
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

# Files and strictness are set in [tool.mypy] in pyproject.toml.
typecheck: _require-dev
	$(PYTHON) -m mypy

# Same shellcheck/actionlint versions as CI (needs Docker).
lint-ci:
	docker run --rm -v "$(CURDIR):/mnt:ro" -w /mnt koalaman/shellcheck:v0.11.0 -s sh get.sh twinfi_cli/data/twinfi-sleep twinfi_cli/data/twinfi.runit
	docker run --rm -v "$(CURDIR):/mnt:ro" -w /mnt koalaman/shellcheck:v0.11.0 install.sh scripts/hardware_check.sh packaging/arch/ci-build.sh packaging/arch/ci-repo.sh packaging/deb/ci-build.sh
	docker run --rm -v "$(CURDIR):/repo" -w /repo rhysd/actionlint:1.7.12

fmt: _require-dev
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

check: lint typecheck coverage

# Run the desktop app from this checkout. The system Python provides the GTK
# bindings (PyGObject); the app calls the `twinfi` from .venv when it exists.
gui:
	PATH="$(CURDIR)/.venv/bin:$$PATH" /usr/bin/python3 twinfi_gtk.py

# Builds every GUI view on a headless display and saves screenshots.
gui-smoke:
	G_DEBUG=fatal-criticals $(PYTHON) scripts/gui_smoke.py gui-screenshots

# Serves the documentation website at http://127.0.0.1:8000 (needs zensical).
site:
	$(PYTHON) scripts/build_site.py
	zensical serve

clean:
	rm -rf build dist *.egg-info .coverage coverage.xml gui-screenshots site-src site
	find . -name __pycache__ -prune -exec rm -rf {} +

_require-dev:
	@$(PYTHON) -c "import coverage, mypy, ruff" 2>/dev/null || { \
		echo "Dev tools (ruff, mypy, coverage) are not installed in $$($(PYTHON) -c 'import sys; print(sys.prefix)')."; \
		echo "Run: make dev"; exit 1; }
