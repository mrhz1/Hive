import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

OCR_ROOT = Path(os.environ.get("BENCH_OCR_ROOT", "/home/cdsw/OCR"))
SAMPLES = Path(os.environ.get("BENCH_SAMPLES", str(OCR_ROOT / "samples" / "AA1234")))
WORK = Path(os.environ.get("BENCH_WORK", "/tmp/ocr-runtime-bench"))
PAGES = int(os.environ.get("BENCH_PAGES", "3"))
ONNX_THREADS = [int(t) for t in os.environ.get("BENCH_THREADS", "2,3,4,8").split(",")]
PADDLE_THREADS = [int(t) for t in os.environ.get("BENCH_PADDLE_THREADS", "3,8").split(",")]
VENV_PYTHON = OCR_ROOT / ".venv-ocr" / "bin" / "python"
MODELS = ["PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"]
DOCS = ["ocr_test_printed_20p", "ocr_test_handwritten_aged_20p"]
LIB = WORK / "onnxlib"
ONNX_MODELS = WORK / "onnx_models"

WORKER = r'''
import json
import logging
import resource
import sys
import time

ocr_root, engine_name, threads, pages, samples, onnx_dir, out = sys.argv[1:8]
threads, pages = int(threads), int(pages)
sys.path.insert(0, ocr_root)
logging.disable(logging.WARNING)

from deid.config import load_config
from deid.ocr_engine import OcrEngine
from deid.pdf_io import open_pdf, render_page

config = load_config()
config.cpu_threads = threads
engine = OcrEngine(config)

if engine_name == "onnx":
    from paddleocr import PaddleOCR

    def load():
        if engine._ocr is None:
            engine._ocr = PaddleOCR(
                text_detection_model_name=config.det_model,
                text_recognition_model_name=config.rec_model,
                text_detection_model_dir=f"{onnx_dir}/{config.det_model}",
                text_recognition_model_dir=f"{onnx_dir}/{config.rec_model}",
                use_doc_orientation_classify=config.use_doc_orientation_classify,
                use_doc_unwarping=config.use_doc_unwarping,
                use_textline_orientation=config.use_textline_orientation,
                device="cpu",
                engine="onnxruntime",
                engine_config={"intra_op_num_threads": threads, "inter_op_num_threads": 1},
            )
        return engine._ocr

    engine._load = load

started = time.perf_counter()
engine._load()
result = {"engine": engine_name, "threads": threads, "load_s": round(time.perf_counter() - started, 1), "docs": {}}
for name in ["ocr_test_printed_20p", "ocr_test_handwritten_aged_20p"]:
    doc = open_pdf(f"{samples}/{name}.pdf")
    engine.read_page(render_page(doc, 0, config.dpi).image)
    done = []
    for index in range(pages):
        image = render_page(doc, index, config.dpi).image
        t = time.perf_counter()
        spans = engine.read_page(image)
        done.append({"seconds": round(time.perf_counter() - t, 2), "lines": [s.text for s in spans]})
        print(f"    {engine_name} {threads}t {name} page {index + 1}: {done[-1]['seconds']} s", flush=True)
    result["docs"][name] = done
result["peak_rss_gb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576, 2)
with open(out, "w") as f:
    json.dump(result, f)
'''


def say(text):
    print(text, flush=True)


def cpu_limit():
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            return round(int(quota) / int(period), 1)
    except (OSError, ValueError):
        pass
    try:
        quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text())
        period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text())
        if quota > 0:
            return round(quota / period, 1)
    except (OSError, ValueError):
        pass
    return None


def cpu_model():
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "unknown"


def checksums():
    found = {}
    for model in MODELS:
        path = OCR_ROOT / "models" / "paddle" / model / "inference.pdiparams"
        found[model] = hashlib.md5(path.read_bytes()).hexdigest()
    return found


def venv_packages():
    done = subprocess.run(
        [str(VENV_PYTHON), "-m", "pip", "freeze"], capture_output=True, text=True
    )
    return set(done.stdout.split())


def install():
    if (LIB / "onnxruntime").is_dir() and (LIB / "paddle2onnx").is_dir():
        say("OK    onnxruntime and paddle2onnx already in the temp folder")
        return
    say("...   installing onnxruntime and paddle2onnx into the temp folder (not the venv)")
    done = subprocess.run(
        [str(VENV_PYTHON), "-m", "pip", "install", "-q", "--target", str(LIB),
         "paddle2onnx==2.0.2rc3", "onnxruntime", "onnx_graphsurgeon==0.6.1", "ml_dtypes==0.6.0"],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout).strip()[-800:])
    for item in LIB.iterdir():
        if item.name.startswith(("numpy", "protobuf")) or item.name == "google":
            shutil.rmtree(item, ignore_errors=True)
    say("OK    installed")


def convert():
    for model in MODELS:
        target = ONNX_MODELS / model
        if (target / "inference.onnx").is_file():
            continue
        target.mkdir(parents=True, exist_ok=True)
        source = OCR_ROOT / "models" / "paddle" / model
        for name in ("inference.yml", "configuration.json"):
            if (source / name).is_file():
                shutil.copy(source / name, target / name)
        code = (
            "import sys; from paddle2onnx.command import main; "
            f"sys.argv=['paddle2onnx','--model_dir',{str(source)!r},"
            "'--model_filename','inference.json','--params_filename','inference.pdiparams',"
            f"'--save_file',{str(target / 'inference.onnx')!r},'--opset_version','17']; main()"
        )
        done = subprocess.run(
            [str(VENV_PYTHON), "-c", code],
            env={**os.environ, "PYTHONPATH": str(LIB), "PIP_TARGET": str(LIB)},
            capture_output=True,
            text=True,
        )
        if not (target / "inference.onnx").is_file():
            raise RuntimeError(f"conversion of {model} failed: {(done.stderr or done.stdout)[-800:]}")
    say("OK    approved models converted into the temp folder")


def run(engine, threads):
    out = WORK / f"result_{engine}_{threads}.json"
    say(f"...   {engine} with {threads} threads")
    env = {
        **os.environ,
        "PYTHONPATH": str(LIB),
        "PIP_TARGET": str(LIB),
        "OCR_CPU_THREADS": str(threads),
        "OMP_NUM_THREADS": str(threads),
        "MKL_NUM_THREADS": str(threads),
    }
    done = subprocess.run(
        [str(VENV_PYTHON), str(WORK / "worker.py"), str(OCR_ROOT), engine, str(threads),
         str(PAGES), str(SAMPLES), str(ONNX_MODELS), str(out)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    for line in done.stdout.splitlines():
        if line.startswith("    "):
            say(line)
    if done.returncode != 0 or not out.is_file():
        tail = "\n".join(line for line in done.stdout.splitlines() if "Warning" not in line)[-800:]
        say(f"FAIL  {engine} {threads}t:\n{tail}")
        return None
    return json.loads(out.read_text())


def norm(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def expected_identifiers(name):
    truth = (SAMPLES / f"{name}.groundtruth.txt").read_text(encoding="utf-8")
    pages = [p for p in re.split(r"=== PAGE \d+ ===", truth) if p.strip()]
    on_pages = norm(" ".join(pages[:PAGES]))
    items = []
    for line in (SAMPLES / f"{name}.phi.txt").read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        value = line.split("\t", 1)[1]
        if norm(value) and norm(value) in on_pages:
            items.append(value)
    return items


def report(results):
    base = next((r for r in results if r["engine"] == "paddle" and r["threads"] == max(PADDLE_THREADS)), results[0])
    summary = []
    for name in DOCS:
        expected = expected_identifiers(name)
        say(f"\n{name} (first {PAGES} pages, {len(expected)} identifiers)")
        say(f"  {'engine':14s}{'s/page':>8s}{'vs paddle':>11s}{'identifiers':>13s}{'text same':>11s}")
        base_pages = [" ".join(p["lines"]) for p in base["docs"][name]]
        base_speed = sum(p["seconds"] for p in base["docs"][name]) / PAGES
        for r in results:
            doc = r["docs"][name]
            speed = sum(p["seconds"] for p in doc) / PAGES
            text = norm(" ".join(" ".join(p["lines"]) for p in doc))
            found = sum(norm(v) in text for v in expected)
            same = sum(
                difflib.SequenceMatcher(None, a, " ".join(p["lines"])).ratio()
                for a, p in zip(base_pages, doc)
            ) / PAGES * 100
            label = f"{r['engine']} {r['threads']}t"
            say(f"  {label:14s}{speed:8.2f}{base_speed / speed:10.2f}x{found:>8d}/{len(expected):<4d}{same:10.2f}%")
            summary.append({"doc": name, "engine": r["engine"], "threads": r["threads"],
                            "seconds_per_page": round(speed, 2), "identifiers": f"{found}/{len(expected)}",
                            "text_same_percent": round(same, 2)})
    say("")
    for r in results:
        say(f"  {r['engine']} {r['threads']}t: model load {r['load_s']} s, peak memory {r['peak_rss_gb']} GB")
    (WORK / "summary.json").write_text(json.dumps(summary, indent=2))
    say(f"\nsaved {WORK / 'summary.json'}")


def main():
    say(f"cpu: {cpu_model()}, cores seen {os.cpu_count()}, session limit {cpu_limit() or 'none found'} vCPU")
    for path in [VENV_PYTHON] + [SAMPLES / f"{d}{s}" for d in DOCS for s in (".pdf", ".groundtruth.txt", ".phi.txt")]:
        if not path.exists():
            say(f"FAIL  missing {path}")
            return
    limit = cpu_limit()
    if limit and max(ONNX_THREADS + PADDLE_THREADS) > limit:
        say(f"NOTE  the largest thread count is above the session's {limit} vCPU; those timings will be slow")

    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "worker.py").write_text(WORKER)
    before = checksums()
    packages = venv_packages()
    try:
        install()
        convert()
    except Exception as exc:
        say(f"FAIL  {exc}")
        return

    started = time.time()
    results = []
    for threads in PADDLE_THREADS:
        results.append(run("paddle", threads))
    for threads in ONNX_THREADS:
        results.append(run("onnx", threads))
    results = [r for r in results if r]
    say(f"\nfinished in {round((time.time() - started) / 60, 1)} min")

    say("OK    approved model files unchanged" if checksums() == before else "FAIL  model files changed")
    now = venv_packages()
    if now == packages:
        say("OK    OCR venv unchanged")
    else:
        say(f"FAIL  OCR venv changed: added {sorted(now - packages)}, removed {sorted(packages - now)}")
    if results:
        report(results)


if __name__ == "__main__":
    main()
