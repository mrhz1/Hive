PYTHON := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: venv install models sample run verify clean

# Torch must come from the CPU index first, or pip pulls the ~2.5GB CUDA build.
venv:
	python3.10 -m venv .venv
	$(PIP) install --upgrade pip

install:
	$(PIP) install --retries 10 --resume-retries 20 --timeout 120 \
		torch --index-url https://download.pytorch.org/whl/cpu
	$(PIP) install --retries 10 --resume-retries 20 --timeout 120 -r requirements.txt
	$(PYTHON) -m spacy download en_core_web_sm

# Pre-fetch every weight. Run at environment build time -- job runs
# should not download hundreds of MB on first request.
models:
	$(PYTHON) scripts/download_models.py

sample:
	$(PYTHON) scripts/make_sample_pdf.py samples/sample_scanned.pdf

# Smoke run over the synthetic document.
run: sample
	$(PYTHON) scripts/run_deid.py --input samples/sample_scanned.pdf --output-dir out

# The check that actually matters: re-OCR the output and fail if any
# planted PII survived, or if the clinical content was over-redacted.
verify:
	$(PYTHON) scripts/verify_redaction.py out/sample_scanned_deid.pdf

clean:
	rm -rf out
