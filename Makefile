INPUT_DIR ?= data/input
OUTPUT_DIR ?= submission/output
LABELS ?= data/reference/public_labeled_pairs.jsonl
PYTHON ?= python
export PYTHONPATH := src

.PHONY: help install test test-fast run profile verify validate-inputs score accept accept-strict determinism docker-build docker-run clean

help:
	@echo "make install        install pinned dev dependencies"
	@echo "make run            full canonicalization run"
	@echo "make test           unit, scenario and full-dataset tests"
	@echo "make test-fast      everything except the full-dataset run"
	@echo "make accept         run + input validators + verify + public scorer"
	@echo "make accept-strict  same, but with the supplied validate_submission.py"
	@echo "                    (does not scale; see docs/FINDINGS.md section 7)"
	@echo "make determinism    two runs, compare output hashes"
	@echo "make docker-build   build the reproducible image"

install:
	$(PYTHON) -m pip install -r requirements-dev.txt

test:
	$(PYTHON) -m pytest

test-fast:
	$(PYTHON) -m pytest -m "not slow"

run:
	$(PYTHON) -m graphcanon run --input-dir $(INPUT_DIR) --output-dir $(OUTPUT_DIR)

profile:
	$(PYTHON) -m graphcanon profile --input-dir $(INPUT_DIR)

validate-inputs:
	$(PYTHON) tools/validate_inputs.py $(INPUT_DIR)
	$(PYTHON) tools/validate_fictionalization.py $(INPUT_DIR)

verify:
	$(PYTHON) -m graphcanon verify --input-dir $(INPUT_DIR) --output-dir $(OUTPUT_DIR)

score:
	$(PYTHON) tools/score_public_pairs.py $(LABELS) $(OUTPUT_DIR)

accept: validate-inputs run verify score

accept-strict: validate-inputs run
	$(PYTHON) tools/validate_submission.py $(INPUT_DIR) $(OUTPUT_DIR)
	$(PYTHON) tools/score_public_pairs.py $(LABELS) $(OUTPUT_DIR)

# quality_report.json is excluded on purpose: it records measured runtime, which
# does not repeat and is not part of the canonical result.
determinism:
	$(PYTHON) -m graphcanon run --input-dir $(INPUT_DIR) --output-dir .determinism/run-a
	$(PYTHON) -m graphcanon run --input-dir $(INPUT_DIR) --output-dir .determinism/run-b
	@cd .determinism && for f in run-a/*.jsonl; do \
		cmp -s "$$f" "run-b/$$(basename $$f)" || { echo "MISMATCH: $$f"; exit 1; }; \
	done && echo "determinism: all JSONL outputs byte-identical"

docker-build:
	docker build -t graphcanon .

docker-run:
	docker run --rm -v "$(PWD)/data:/app/data:ro" -v "$(PWD)/$(OUTPUT_DIR):/app/$(OUTPUT_DIR)" graphcanon

clean:
	rm -rf .determinism $(OUTPUT_DIR)/*.jsonl $(OUTPUT_DIR)/*.json
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
