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

install-nlp:
	$(NLP_PIP) install $(PIP_FLAGS) torch \
		--index-url https://download.pytorch.org/whl/cpu
	$(NLP_PIP) install $(PIP_FLAGS) -r requirements-nlp.txt

models: models-ocr models-nlp

models-ocr:
	$(OCR_PYTHON) scripts/stage_models.py --stage ocr

models-nlp:
	$(NLP_PYTHON) scripts/stage_models.py --stage nlp

check-models: check-models-ocr check-models-nlp

check-models-ocr:
	$(OCR_PYTHON) scripts/check_models.py --stage ocr

check-models-nlp:
	$(NLP_PYTHON) scripts/check_models.py --stage nlp

preflight:
	$(PYTHON) scripts/run_deid.py --preflight

sample:
	$(OCR_PYTHON) scripts/make_sample_pdf.py samples/sample_scanned.pdf

run: sample
	$(PYTHON) scripts/run_deid.py --input samples/sample_scanned.pdf --output-dir out

verify:
	$(OCR_PYTHON) scripts/verify_redaction.py out/sample_scanned_deid.pdf

clean:
	rm -rf out

distclean: clean
	rm -rf .venv-ocr .venv-nlp
