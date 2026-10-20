import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

INSTALL_APP = True
INSTALL_OCR = True
INSTALL_NLP = True

PIP_FLAGS = ["--retries", "10", "--timeout", "120"]
TORCH_INDEX = "https://download.pytorch.org/whl/cpu"


def repo_root():
    here = globals().get("__file__")
    candidates = []
    if here:
        own = Path(here).resolve().parent
        candidates += [own, own.parent]
    for var in ("HIVE_REPO_ROOT", "CDSW_PROJECT_DIR"):
        if os.environ.get(var):
            candidates.append(Path(os.environ[var]))
    cwd = Path.cwd().resolve()
    candidates += [cwd, cwd.parent, Path("/home/cdsw")]
    for candidate in candidates:
        if (candidate / "OCR" / "requirements-ocr.txt").is_file():
            return candidate
    raise RuntimeError("Cannot find the project folder; set HIVE_REPO_ROOT")


def run(label, command, cwd):
    print(f"\n=== {label}\n$ {' '.join(str(c) for c in command)}", flush=True)
    started = time.time()
    done = subprocess.run([str(c) for c in command], cwd=str(cwd))
    took = round(time.time() - started)
    if done.returncode != 0:
        print(f"FAIL  {label} (exit {done.returncode}, {took}s)", flush=True)
        return False
    print(f"OK    {label} ({took}s)", flush=True)
    return True


def base_python():
    return shutil.which("python3.10") or sys.executable


def venv(folder, ocr_dir):
    python = ocr_dir / folder / "bin" / "python"
    if python.is_file():
        return python
    if not run(f"create {folder}", [base_python(), "-m", "venv", folder], ocr_dir):
        return None
    run(f"upgrade pip in {folder}", [python, "-m", "pip", "install", "--upgrade", "pip"], ocr_dir)
    return python


def check(label, python, modules, cwd):
    code = "; ".join(f"import {m}" for m in modules) + "; print('imports ok')"
    return run(f"check {label}: {', '.join(modules)}", [python, "-c", code], cwd)


def main():
    root = repo_root()
    ocr_dir = root / "OCR"
    print(f"project {root}\npython  {sys.executable}", flush=True)
    results = {}

    if INSTALL_APP:
        results["app"] = run(
            "app requirements (API, Jobs)",
            [sys.executable, "-m", "pip", "install", *PIP_FLAGS, "-r", root / "requirements-dev.txt"],
            root,
        ) and check("app", sys.executable, ["pydicom", "fitz", "docx", "smbclient"], root)

    if INSTALL_OCR:
        python = venv(".venv-ocr", ocr_dir)
        results["ocr"] = bool(python) and run(
            "OCR requirements (.venv-ocr)",
            [python, "-m", "pip", "install", *PIP_FLAGS, "-r", "requirements-ocr.txt"],
            ocr_dir,
        ) and check("ocr", python, ["pydicom", "fitz", "paddleocr"], ocr_dir)

    if INSTALL_NLP:
        python = venv(".venv-nlp", ocr_dir)
        results["nlp"] = bool(python) and run(
            "CPU torch (.venv-nlp)",
            [python, "-m", "pip", "install", *PIP_FLAGS, "torch", "--index-url", TORCH_INDEX],
            ocr_dir,
        ) and run(
            "NLP requirements (.venv-nlp)",
            [python, "-m", "pip", "install", *PIP_FLAGS, "-r", "requirements-nlp.txt"],
            ocr_dir,
        ) and check("nlp", python, ["pydicom", "fitz", "docx", "presidio_analyzer", "spacy"], ocr_dir)

    print("\n=== summary")
    for name, ok in results.items():
        print(f"{'OK  ' if ok else 'FAIL'}  {name}")
    if all(results.values()):
        print("\nAll installed. Restart the API Application and the Jobs so they pick it up.")


if __name__ == "__main__":
    main()
