# Makefile for Ethics Request Pipeline

.PHONY: help install dirs test e2e demo known-good known-bad head-to-head golden-dataset-report export-review-sheet run render batch clean

.DEFAULT_GOAL := help
PYTHON ?= python
OUTPUT_DIR := output
DEV_RUNS_DIR := $(OUTPUT_DIR)/dev_runs
BATCH_DIR := $(OUTPUT_DIR)/batch_analysis
KNOWN_GOOD_DIR := examples/known-good
KNOWN_BAD_DIR := examples/known-bad
HEAD_TO_HEAD_DIR := examples/head-to-head

help:
	@echo "Available targets:"
	@echo "  make install        # Install Python dependencies"
	@echo "  make test           # Run full pytest suite"
	@echo "  make e2e            # Run deterministic end-to-end pipeline tests"
	@echo "  make demo           # Parse + lint demo HTML"
	@echo "  make run FILE=...   # Parse + lint a specific HTML export"
	@echo "  make render JSON=.. # Render a JSON instance back to HTML"
	@echo "  make known-good     # Batch lint all Known Good examples"
	@echo "  make known-bad      # Batch lint Known Bad examples (expect failures)"
	@echo "  make head-to-head   # Run manifest-driven golden dataset regression tests"
	@echo "  make golden-dataset-report # Summarize golden dataset coverage and blockers"
	@echo "  make export-review-sheet   # Export reviewer-ready CSV to output/"
	@echo "  make batch INPUT=.. # Batch analyze any directory of HTML exports"
	@echo "  make clean          # Remove cache dirs + dev run artifacts"

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

### Utility targets ###

dirs:
	@mkdir -p $(DEV_RUNS_DIR) $(BATCH_DIR)

### Core workflows ###

test:
	$(PYTHON) -m pytest tests/

e2e:
	$(PYTHON) -m pytest tests/test_e2e_pipeline.py

demo: dirs
	@stem=$$(basename examples/demo_render.html .html); \
	json="$(DEV_RUNS_DIR)/$${stem}.json"; \
	report="$(DEV_RUNS_DIR)/$${stem}_report.json"; \
	$(PYTHON) src/html_to_json.py examples/demo_render.html "$$json"; \
	$(PYTHON) -m src.linter_renderer lint "$$json" --report "$$report"
	@echo "Demo artifacts written to $(DEV_RUNS_DIR)"

run: dirs
	@[ -n "$(FILE)" ] || (echo "Usage: make run FILE=path/to/file.html" && exit 1)
	@stem=$$(basename "$(FILE)" .html); \
	json="$(DEV_RUNS_DIR)/$${stem}.json"; \
	report="$(DEV_RUNS_DIR)/$${stem}_report.json"; \
	$(PYTHON) src/html_to_json.py "$(FILE)" "$$json"; \
	$(PYTHON) -m src.linter_renderer lint "$$json" --report "$$report"; \
	echo "Parsed + linted: $(FILE)"; \
	echo "JSON => $$json"; \
	echo "Report => $$report"

render: dirs
	@[ -n "$(JSON)" ] || (echo "Usage: make render JSON=path/to/file.json" && exit 1)
	@stem=$$(basename "$(JSON)" .json); \
	html="$(DEV_RUNS_DIR)/$${stem}_render.html"; \
	$(PYTHON) -m src.linter_renderer render "$(JSON)" --html "$$html"; \
	echo "Rendered HTML => $$html"

known-good:
	$(PYTHON) scripts/batch_process.py $(KNOWN_GOOD_DIR) --fail-on-error

known-bad:
	-$(PYTHON) scripts/batch_process.py $(KNOWN_BAD_DIR)

head-to-head:
	$(PYTHON) -m pytest tests/test_golden_dataset.py

golden-dataset-report: dirs
	$(PYTHON) scripts/golden_dataset_report.py --output $(DEV_RUNS_DIR)/golden_dataset_report.json

export-review-sheet: dirs
	$(PYTHON) scripts/export_reviewer_sheet.py --output $(DEV_RUNS_DIR)/golden_dataset_review_sheet.csv

batch:
	@[ -n "$(INPUT)" ] || (echo "Usage: make batch INPUT=path/to/html_dir [ARGS=...]" && exit 1)
	$(PYTHON) scripts/batch_process.py "$(INPUT)" $(ARGS)

clean:
	rm -rf $(DEV_RUNS_DIR)
	rm -rf .pytest_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
