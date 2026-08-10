"""Guards on the two-virtualenv split in OCR/."""
import ast
import subprocess
import sys
from pathlib import Path

import pytest

OCR_ROOT = Path(__file__).resolve().parent.parent / "OCR"

# Modules either stage may import, so they may not touch either stack.
SHARED_MODULES = [
    "deid.config",
    "deid.spans",
    "deid.results",
    "deid.mapping",
    "deid.model_store",
]

# (module, forbidden import prefixes)
STAGE_BOUNDARIES = [
    ("deid/stage_ocr.py", ("deid.analyzer", "deid.recognizers", "deid.stage_nlp")),
    ("deid/ocr_engine.py", ("deid.analyzer", "deid.recognizers", "deid.stage_nlp")),
    ("deid/stage_nlp.py", ("deid.ocr_engine", "deid.stage_ocr")),
    ("deid/analyzer.py", ("deid.ocr_engine", "deid.stage_ocr")),
    ("deid/recognizers.py", ("deid.ocr_engine", "deid.stage_ocr")),
    # The shared ones must reach into neither.
    ("deid/mapping.py", ("deid.analyzer", "deid.ocr_engine", "deid.recognizers")),
    ("deid/pdf_io.py", ("deid.analyzer", "deid.ocr_engine", "deid.recognizers")),
    ("deid/pipeline.py", ("deid.analyzer", "deid.ocr_engine", "deid.stage_ocr",
                          "deid.stage_nlp", "deid.recognizers")),
    ("deid/model_store.py", ("deid.analyzer", "deid.ocr_engine",
                             "deid.recognizers", "deid.stage_ocr",
                             "deid.stage_nlp")),
]

PADDLE_PACKAGES = ("paddle", "paddleocr", "paddlex")
NLP_PACKAGES = ("presidio_analyzer", "presidio_anonymizer", "transformers",
                "spacy", "torch")


def _imported_names(path: Path):
    """Every module name imported by `path`, at any nesting level."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("module_path,forbidden", STAGE_BOUNDARIES)
def test_stage_modules_do_not_import_across_the_split(module_path, forbidden):
    imported = _imported_names(OCR_ROOT / module_path)
    offenders = sorted(
        name
        for name in imported
        if any(name == f or name.startswith(f + ".") for f in forbidden)
    )
    assert not offenders, (
        f"{module_path} imports {offenders}, which lives in the other "
        f"virtualenv. The two stacks cannot be installed together -- move "
        f"the shared piece into deid/spans.py instead."
    )


@pytest.mark.parametrize(
    "module_path,packages",
    [
        ("deid/config.py", PADDLE_PACKAGES + NLP_PACKAGES),
        ("deid/spans.py", PADDLE_PACKAGES + NLP_PACKAGES),
        ("deid/results.py", PADDLE_PACKAGES + NLP_PACKAGES),
        ("deid/mapping.py", PADDLE_PACKAGES + NLP_PACKAGES),
        ("deid/pipeline.py", PADDLE_PACKAGES + NLP_PACKAGES),
        ("deid/model_store.py", PADDLE_PACKAGES + NLP_PACKAGES),
        ("scripts/run_deid.py", PADDLE_PACKAGES + NLP_PACKAGES),
        ("deid/stage_ocr.py", NLP_PACKAGES),
        ("deid/stage_nlp.py", PADDLE_PACKAGES),
    ],
)
def test_modules_do_not_import_the_wrong_stack(module_path, packages):
    imported = _imported_names(OCR_ROOT / module_path)
    offenders = sorted(
        name
        for name in imported
        if any(name == p or name.startswith(p + ".") for p in packages)
    )
    assert not offenders, f"{module_path} imports {offenders}"


def test_orchestrator_runs_with_nothing_installed():
    """--preflight under an interpreter with no ML stack at all."""
    completed = subprocess.run(
        [sys.executable, str(OCR_ROOT / "scripts" / "run_deid.py"), "--preflight"],
        capture_output=True,
        text=True,
        cwd=str(OCR_ROOT),
    )

    assert completed.returncode in (0, 1), completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr, completed.stderr
    assert '"ocr_python"' in completed.stdout, completed.stdout


def test_requirements_files_stay_apart():
    """The two requirement sets must not name each other's stack, and the combined requirements.txt must stay deleted -- installing it is the exact thing that does not work."""
    assert not (OCR_ROOT / "requirements.txt").exists(), (
        "OCR/requirements.txt is back; a single combined requirement set "
        "cannot be resolved (paddlex pins PyYAML==6.0.2 against "
        "presidio-analyzer's pyyaml>=6.0.3)"
    )

    ocr_reqs = (OCR_ROOT / "requirements-ocr.txt").read_text()
    nlp_reqs = (OCR_ROOT / "requirements-nlp.txt").read_text()

    def requirement_lines(text):
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    assert not [line for line in requirement_lines(ocr_reqs) if "presidio" in line]
    assert not [line for line in requirement_lines(nlp_reqs) if "paddle" in line]


@pytest.mark.parametrize("module", SHARED_MODULES)
def test_shared_modules_import_under_the_api_venv(module):
    """They are imported by the orchestrator, which runs wherever."""
    completed = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        cwd=str(OCR_ROOT),
    )
    assert completed.returncode == 0, completed.stderr
