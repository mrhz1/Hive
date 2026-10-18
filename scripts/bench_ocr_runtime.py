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
FILES = Path(os.environ.get("BENCH_FILES", str(OCR_ROOT / "samples" / "AA1234")))
MAX_FILES = int(os.environ.get("BENCH_MAX_FILES", "4"))
WORK = Path(os.environ.get("BENCH_WORK", "/tmp/ocr-runtime-bench"))
PAGES = int(os.environ.get("BENCH_PAGES", "3"))
ONNX_THREADS = [int(t) for t in os.environ.get("BENCH_THREADS", "").split(",") if t.strip()]
PADDLE_THREADS = [int(t) for t in os.environ.get("BENCH_PADDLE_THREADS", "").split(",") if t.strip()]
PARALLEL = [
    (engine.strip(), int(setup.split("x")[0]), int(setup.split("x")[1]))
    for engine, setup in (
        item.split(":") for item in os.environ.get("BENCH_PARALLEL", "paddle:3x5,onnx:8x2").split(",") if item.strip()
    )
]
VENV_PYTHON = OCR_ROOT / ".venv-ocr" / "bin" / "python"
MODELS = ["PP-OCRv6_medium_det", "PP-OCRv6_medium_rec"]
LIB = WORK / "onnxlib"
ONNX_MODELS = WORK / "onnx_models"

WORKER = r'''
import json
import logging
import os
import resource
import sys
import time

ocr_root, engine_name, threads, pages, files, onnx_dir, out, go = sys.argv[1:9]
threads, pages = int(threads), int(pages)
sys.path.insert(0, ocr_root)
logging.disable(logging.WARNING)

import fitz
import numpy as np

from deid.config import load_config
from deid.ocr_engine import OcrEngine


def render_page(doc, index, dpi):
    scale = dpi / 72.0
    pix = doc[index].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    return np.ascontiguousarray(image[:, :, :3])

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
paths = json.load(open(files))
engine.read_page(render_page(fitz.open(paths[0]), 0, config.dpi))
if go != "-":
    open(f"{out}.ready", "w").close()
    while not os.path.exists(go):
        time.sleep(0.2)
result["ocr_start"] = time.time()
cpu_start = time.process_time()
for number, path in enumerate(paths, start=1):
    name = f"file {number}"
    doc = fitz.open(path)
    done = []
    for index in range(min(pages, doc.page_count)):
        image = render_page(doc, index, config.dpi)
        t = time.perf_counter()
        spans = engine.read_page(image)
        done.append({"seconds": round(time.perf_counter() - t, 2), "lines": [s.text for s in spans]})
        print(f"    {engine_name} {threads}t {name} page {index + 1}: {done[-1]['seconds']} s", flush=True)
    result["docs"][name] = done
result["ocr_end"] = time.time()
result["cpu_s"] = time.process_time() - cpu_start
result["peak_rss_gb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576, 2)
with open(out, "w") as f:
    json.dump(result, f)
'''


def say(text):
    print(text, flush=True)


def cpu_limit():
    for name in ("CDSW_CPU_MILLICORES", "CML_CPU_MILLICORES"):
        try:
            return round(int(os.environ[name]) / 1000, 1)
        except (KeyError, ValueError):
            pass
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()
        if quota != "max":
            return round(int(quota) / int(period), 1)
    except (OSError, ValueError):
        pass
    for folder in ("/sys/fs/cgroup/cpu", "/sys/fs/cgroup/cpu,cpuacct", "/sys/fs/cgroup/cpuacct,cpu"):
        try:
            quota = int(Path(folder, "cpu.cfs_quota_us").read_text())
            period = int(Path(folder, "cpu.cfs_period_us").read_text())
            if quota > 0:
                return round(quota / period, 1)
        except (OSError, ValueError):
            pass
    try:
        usable = len(os.sched_getaffinity(0))
        if usable < (os.cpu_count() or usable):
            return float(usable)
    except (AttributeError, OSError):
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


def python_path():
    existing = os.environ.get("PYTHONPATH", "")
    return os.pathsep.join([str(LIB)] + ([existing] if existing else []))


def check_imports():
    code = (
        "import google.protobuf as p, paddle, numpy; "
        "print('protobuf', p.__version__, p.__file__); print('paddle', paddle.__version__); "
        "print('numpy', numpy.__version__, numpy.__file__)"
    )
    for label, env in (
        ("without the temp folder", dict(os.environ)),
        ("with the temp folder", {**os.environ, "PYTHONPATH": python_path()}),
    ):
        done = subprocess.run([str(VENV_PYTHON), "-c", code], env=env, capture_output=True, text=True)
        if done.returncode == 0:
            say(f"OK    imports {label}: " + " | ".join(done.stdout.split("\n")).strip(" |"))
        else:
            say(f"FAIL  imports {label}: {(done.stderr or done.stdout).strip().splitlines()[-1]}")
            return False
    return True


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
        env={**os.environ, "PIP_USER": "0"},
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
            env={**os.environ, "PYTHONPATH": python_path(), "PIP_TARGET": str(LIB), "PIP_USER": "0"},
            capture_output=True,
            text=True,
        )
        if not (target / "inference.onnx").is_file():
            raise RuntimeError(f"conversion of {model} failed: {(done.stderr or done.stdout)[-800:]}")
    say("OK    approved models converted into the temp folder")


def worker_env(threads):
    return {
        **os.environ,
        "PYTHONPATH": python_path(),
        "PIP_TARGET": str(LIB),
        "PIP_USER": "0",
        "OCR_CPU_THREADS": str(threads),
        "OMP_NUM_THREADS": str(threads),
        "MKL_NUM_THREADS": str(threads),
    }


def worker_command(engine, threads, out, go="-"):
    return [str(VENV_PYTHON), str(WORK / "worker.py"), str(OCR_ROOT), engine, str(threads),
            str(PAGES), str(WORK / "files.json"), str(ONNX_MODELS), str(out), str(go)]


def run(engine, threads):
    out = WORK / f"result_{engine}_{threads}.json"
    say(f"...   {engine} with {threads} threads")
    done = subprocess.run(
        worker_command(engine, threads, out),
        env=worker_env(threads),
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


def run_parallel(engine, threads, workers):
    say(f"...   {engine} {threads}t x {workers} workers at the same time")
    go = WORK / f"go_{engine}_{threads}_{workers}"
    go.unlink(missing_ok=True)
    outs, logs, procs = [], [], []
    for number in range(1, workers + 1):
        out = WORK / f"result_{engine}_{threads}_x{workers}_w{number}.json"
        log = WORK / f"log_{engine}_{threads}_x{workers}_w{number}.txt"
        out.unlink(missing_ok=True)
        Path(f"{out}.ready").unlink(missing_ok=True)
        with open(log, "w") as handle:
            procs.append(subprocess.Popen(
                worker_command(engine, threads, out, go),
                env=worker_env(threads),
                stdout=handle,
                stderr=subprocess.STDOUT,
            ))
        outs.append(out)
        logs.append(log)
    while not all(Path(f"{o}.ready").exists() for o in outs):
        if any(p.poll() is not None for p in procs):
            break
        time.sleep(0.5)
    say(f"      all {workers} workers loaded, starting together")
    go.touch()
    for p in procs:
        p.wait()
    go.unlink(missing_ok=True)
    results = []
    for out, log, p in zip(outs, logs, procs):
        Path(f"{out}.ready").unlink(missing_ok=True)
        if p.returncode != 0 or not out.is_file():
            tail = "\n".join(line for line in log.read_text().splitlines() if "Warning" not in line)[-800:]
            say(f"FAIL  {engine} {threads}t worker {log.stem[-1]}:\n{tail}")
            continue
        results.append(json.loads(out.read_text()))
        log.unlink(missing_ok=True)
    if len(results) < workers:
        return None
    span = max(r["ocr_end"] for r in results) - min(r["ocr_start"] for r in results)
    page_times = [p["seconds"] for r in results for doc in r["docs"].values() for p in doc]
    found = {
        "engine": engine,
        "threads": threads,
        "workers": workers,
        "pages": len(page_times),
        "minutes": round(span / 60, 1),
        "pages_per_hour": round(len(page_times) / span * 3600, 1),
        "seconds_per_page_each_worker": round(sum(page_times) / len(page_times), 2),
        "cores_used": round(sum(r["cpu_s"] for r in results) / span, 1),
        "memory_gb": round(sum(r["peak_rss_gb"] for r in results), 2),
    }
    say(f"      done: {found['pages']} pages in {found['minutes']} min")
    return found


def report_parallel(found):
    say(f"\nparallel (all workers at the same time, first {PAGES} pages of each file per worker)")
    say(f"  {'setup':16s}{'pages/hour':>11s}{'s/page':>9s}{'cores used':>12s}{'memory':>10s}")
    for f in found:
        label = f"{f['engine']} {f['threads']}t x{f['workers']}"
        say(f"  {label:16s}{f['pages_per_hour']:11.1f}{f['seconds_per_page_each_worker']:9.2f}"
            f"{f['cores_used']:12.1f}{f['memory_gb']:7.2f} GB")
    say("  s/page is how long one page took inside one worker; cores used is CPU time / elapsed time")


def norm(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def pdfs():
    found = sorted(
        p for p in FILES.rglob("*.pdf")
        if not any(part.startswith(".") for part in p.relative_to(FILES).parts)
    )
    return found[:MAX_FILES]


def expected_identifiers(path, pages):
    truth_file = path.with_suffix(".groundtruth.txt")
    phi_file = path.with_suffix(".phi.txt")
    if not (truth_file.is_file() and phi_file.is_file()):
        return None
    truth = truth_file.read_text(encoding="utf-8")
    split = [p for p in re.split(r"=== PAGE \d+ ===", truth) if p.strip()]
    on_pages = norm(" ".join(split[:pages]))
    items = []
    for line in phi_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "\t" not in line:
            continue
        value = line.split("\t", 1)[1]
        if norm(value) and norm(value) in on_pages:
            items.append(value)
    return items


def report(results, files):
    base = next((r for r in results if r["engine"] == "paddle" and r["threads"] == max(PADDLE_THREADS, default=0)), results[0])
    summary = []
    for number, path in enumerate(files, start=1):
        name = f"file {number}"
        base_doc = base["docs"].get(name)
        if not base_doc:
            continue
        pages = len(base_doc)
        expected = expected_identifiers(path, pages)
        title = f"{name}: {path.stem}" if expected is not None else name
        found_text = f", {len(expected)} identifiers" if expected is not None else ", no answer files"
        say(f"\n{title} (first {pages} pages{found_text})")
        say(f"  {'engine':14s}{'s/page':>8s}{'vs paddle':>11s}{'identifiers':>13s}{'text same':>11s}")
        base_pages = [" ".join(p["lines"]) for p in base_doc]
        base_speed = sum(p["seconds"] for p in base_doc) / pages
        for r in results:
            doc = r["docs"].get(name)
            if not doc:
                continue
            speed = sum(p["seconds"] for p in doc) / len(doc)
            text = norm(" ".join(" ".join(p["lines"]) for p in doc))
            if expected is None:
                identifiers = "-"
            else:
                identifiers = f"{sum(norm(v) in text for v in expected)}/{len(expected)}"
            same = sum(
                difflib.SequenceMatcher(None, a, " ".join(p["lines"])).ratio()
                for a, p in zip(base_pages, doc)
            ) / len(doc) * 100
            label = f"{r['engine']} {r['threads']}t"
            say(f"  {label:14s}{speed:8.2f}{base_speed / speed:10.2f}x{identifiers:>13s}{same:10.2f}%")
            summary.append({"file": name, "pages": pages, "engine": r["engine"], "threads": r["threads"],
                            "seconds_per_page": round(speed, 2), "identifiers": identifiers,
                            "text_same_percent": round(same, 2)})
    say("")
    for r in results:
        cores = r["cpu_s"] / (r["ocr_end"] - r["ocr_start"])
        say(f"  {r['engine']} {r['threads']}t: model load {r['load_s']} s, peak memory {r['peak_rss_gb']} GB, "
            f"cores used {cores:.1f}")
    return summary


def main():
    say(f"cpu: {cpu_model()}, cores seen {os.cpu_count()}, session limit {cpu_limit() or 'none found'} vCPU")
    say("      cpu settings: " + ", ".join(
        f"{k}={v}" for k, v in sorted(os.environ.items()) if "CPU" in k or k.endswith("_THREADS")
    ))
    if not VENV_PYTHON.exists():
        say(f"FAIL  missing {VENV_PYTHON}")
        return
    files = pdfs()
    if not files:
        say(f"FAIL  no PDFs found in {FILES} (set BENCH_FILES to a folder with a few PDFs)")
        return
    say(f"OK    {len(files)} PDF(s) from {FILES}, first {PAGES} pages of each")
    limit = cpu_limit()
    if limit and max(ONNX_THREADS + PADDLE_THREADS, default=0) > limit:
        say(f"NOTE  the largest thread count is above the session's {limit} vCPU; those timings will be slow")
    for engine, threads, workers in PARALLEL:
        if limit and threads * workers > limit:
            say(f"NOTE  {engine} {threads}t x{workers} needs {threads * workers} vCPU, the session has {limit}; "
                "use a 16 vCPU session")

    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "worker.py").write_text(WORKER)
    (WORK / "files.json").write_text(json.dumps([str(p) for p in files]))
    before = checksums()
    packages = venv_packages()
    try:
        install()
        if not check_imports():
            say(f"      PYTHONPATH in this session: {os.environ.get('PYTHONPATH') or '(not set)'}")
            return
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
    parallel = [found for found in (run_parallel(*setup) for setup in PARALLEL) if found]
    say(f"\nfinished in {round((time.time() - started) / 60, 1)} min")

    say("OK    approved model files unchanged" if checksums() == before else "FAIL  model files changed")
    now = venv_packages()
    if now == packages:
        say("OK    OCR venv unchanged")
    else:
        say(f"FAIL  OCR venv changed: added {sorted(now - packages)}, removed {sorted(packages - now)}")
    summary = {"one_at_a_time": report(results, files) if results else [], "parallel": parallel}
    if parallel:
        report_parallel(parallel)
    (WORK / "summary.json").write_text(json.dumps(summary, indent=2))
    say(f"\nsaved {WORK / 'summary.json'}")
    for item in list(WORK.glob("result_*.json")) + [WORK / "files.json"]:
        item.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
