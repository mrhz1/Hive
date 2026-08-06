# Two virtualenvs, because paddle and presidio cannot share one:
# paddlex pins PyYAML==6.0.2, presidio-analyzer>=2.2.363 needs >=6.0.3.
# See deid/pipeline.py.
#
# The orchestrator (scripts/run_deid.py) needs neither -- it is stdlib
# only -- so PYTHON below is just whatever python3 is on PATH.
PYTHON     := python3
BASE       := python3.10

OCR_PYTHON := .venv-ocr/bin/python
OCR_PIP    := .venv-ocr/bin/pip
NLP_PYTHON := .venv-nlp/bin/python
NLP_PIP    := .venv-nlp/bin/pip

PIP_FLAGS  := --retries 10 --resume-retries 20 --timeout 120

.PHONY: venvs install install-ocr install-nlp models models-ocr models-nlp \
        check-models check-models-ocr check-models-nlp \
        preflight sample run verify clean distclean

venvs:
	$(BASE) -m venv .venv-ocr
	$(BASE) -m venv .venv-nlp
	$(OCR_PIP) install --upgrade pip
	$(NLP_PIP) install --upgrade pip

install: install-ocr install-nlp

install-ocr:
	$(OCR_PIP) install $(PIP_FLAGS) -r requirements-ocr.txt

# Torch must come from the CPU index FIRST, or pip pulls the ~3GB CUDA
# build for a job that runs on CPU.
install-nlp:
	$(NLP_PIP) install $(PIP_FLAGS) torch \
		--index-url https://download.pytorch.org/whl/cpu
	$(NLP_PIP) install $(PIP_FLAGS) -r requirements-nlp.txt

# Fill models/ from the network. Run this on a machine that HAS network
# access -- Cloudera AI blocks github and huggingface, so the store is
# built here and copied there. Nothing downloads at job time.
models: models-ocr models-nlp

models-ocr:
	$(OCR_PYTHON) scripts/stage_models.py --stage ocr

models-nlp:
	$(NLP_PYTHON) scripts/stage_models.py --stage nlp

# Load every staged model with the network switched off. This is the
# check to run ON the Cloudera node after copying models/ across: it is
# the only one that catches a truncated weight file.
check-models: check-models-ocr check-models-nlp

check-models-ocr:
	$(OCR_PYTHON) scripts/check_models.py --stage ocr

check-models-nlp:
	$(NLP_PYTHON) scripts/check_models.py --stage nlp

# Interpreters resolvable and models present? Cheap, dependency-free, and
# between them those are the two most common ways a deployment is broken.
preflight:
	$(PYTHON) scripts/run_deid.py --preflight

sample:
	$(OCR_PYTHON) scripts/make_sample_pdf.py samples/sample_scanned.pdf

# Smoke run over the synthetic document.
run: sample
	$(PYTHON) scripts/run_deid.py --input samples/sample_scanned.pdf --output-dir out

# The check that actually matters: re-OCR the output and fail if any
# planted PII survived, or if the clinical content was over-redacted.
# Runs in the OCR venv -- verification only needs to read, not detect.
verify:
	$(OCR_PYTHON) scripts/verify_redaction.py out/sample_scanned_deid.pdf

clean:
	rm -rf out

distclean: clean
	rm -rf .venv-ocr .venv-nlp
