import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from deid import model_store
from deid.config import load_config
from deid.results import DocumentResult
from deid.documents import needs_ocr, output_extension
from deid.progress import writer as progress_writer
from deid.spans import write_manifest

log = logging.getLogger(__name__)

OCR_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_OCR_PYTHON = str(OCR_ROOT / ".venv-ocr" / "bin" / "python")
DEFAULT_NLP_PYTHON = str(OCR_ROOT / ".venv-nlp" / "bin" / "python")


def ocr_python() -> str:
    return os.environ.get("DEID_OCR_PYTHON", DEFAULT_OCR_PYTHON)


def nlp_python() -> str:
    return os.environ.get("DEID_NLP_PYTHON", DEFAULT_NLP_PYTHON)


def _is_on(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


class StageError(RuntimeError):
    pass


def _failure_detail(stderr: str, stdout: str) -> str:
    text = (stderr or stdout or "").strip()
    errors = [
        line
        for line in text.splitlines()
        if "ERROR" in line or "Traceback" in line or "Error:" in line
    ]
    detail = " | ".join(errors) if errors else text
    return detail.strip()[-800:]


def _run_stage(
    interpreter: str,
    script: str,
    manifest_path: str,
    result_path: str,
    stage: str,
) -> List[dict]:
    command = [
        interpreter,
        str(OCR_ROOT / "scripts" / script),
        "--manifest",
        manifest_path,
        "--result",
        result_path,
    ]
    log.info("stage %s: %s", stage, " ".join(command))

    try:
        completed = subprocess.run(
            command,
            cwd=str(OCR_ROOT),
            capture_output=True,
            text=True,
            check=False,
            env=os.environ.copy(),
        )
    except FileNotFoundError as e:
        raise StageError(
            f"{stage} stage interpreter not found at '{interpreter}'. "
            f"Set DEID_{stage.upper()}_PYTHON to the venv that has the "
            f"{stage} dependencies installed."
        ) from e

    if completed.stderr and (completed.returncode != 0 or _is_on("DEID_LOG_STAGE_OUTPUT")):
        for line in completed.stderr.strip().splitlines():
            log.info("[%s] %s", stage, line)

    if not os.path.exists(result_path):
        detail = _failure_detail(completed.stderr, completed.stdout)
        raise StageError(
            f"{stage} stage produced no result file "
            f"(exit {completed.returncode}): {detail}"
        )

    with open(result_path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def ocr_batch_size() -> int:
    try:
        return max(1, int(os.environ.get("DEID_OCR_BATCH_SIZE", "1")))
    except ValueError:
        return 1


def _fail_all(sources: List[str], stage: str, error: str) -> List[DocumentResult]:
    return [
        DocumentResult(
            source_path=source, status="error", error=error, failed_stage=stage
        )
        for source in sources
    ]


def run_pipeline(
    sources: List[str],
    output_dir: str,
    suffix: str = "_deid",
    work_dir: Optional[str] = None,
    progress_path: Optional[str] = None,
) -> List[DocumentResult]:
    if not sources:
        return []

    output_root = Path(output_dir).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)

    keep_work_dir = _is_on("DEID_KEEP_WORK_DIR")

    if work_dir:
        work = Path(work_dir).expanduser()
        work.mkdir(parents=True, mode=0o700, exist_ok=True)
        owned = False
    else:
        work = Path(tempfile.mkdtemp(prefix="deid-work-"))
        owned = True

    try:
        return _run(sources, output_root, suffix, work, progress_path)
    finally:
        if owned and not keep_work_dir:
            shutil.rmtree(work, ignore_errors=True)
        elif keep_work_dir:
            log.warning(
                "DEID_KEEP_WORK_DIR is set: OCR text (PHI) left in %s", work
            )


def _run_nlp(jobs: List[Dict[str, Any]], work: Path) -> List[DocumentResult]:
    if not jobs:
        return []

    nlp_manifest = str(work / "nlp-manifest.json")
    write_manifest(nlp_manifest, jobs)

    try:
        nlp_results = _run_stage(
            nlp_python(),
            "stage_nlp.py",
            nlp_manifest,
            str(work / "nlp-result.json"),
            "nlp",
        )
        return [DocumentResult.from_dict(r) for r in nlp_results]
    except StageError as e:
        log.error("NLP stage failed: %s", e)
        return _fail_all([j["source"] for j in jobs], "nlp", str(e))


def _run(
    sources: List[str],
    output_root: Path,
    suffix: str,
    work: Path,
    progress_path: Optional[str] = None,
) -> List[DocumentResult]:
    plan: List[Dict[str, Any]] = []
    for index, source in enumerate(sources):
        stem = Path(source).stem + suffix
        plan.append(
            {
                "source": source,
                "spans": str(work / f"{index:05d}.spans.json"),
                "output_pdf": str(output_root / f"{stem}{output_extension(source)}"),
                "output_text": str(output_root / f"{stem}.txt"),
                "output_report": str(output_root / f"{stem}.report.json"),
                "progress": progress_path,
                "index": index,
                "file_total": len(sources),
            }
        )

    rasterizable = [j for j in plan if needs_ocr(j["source"])]
    text_only = [j for j in plan if not needs_ocr(j["source"])]

    ocr_status: Dict[str, Any] = {}
    ocr_failures: List[DocumentResult] = []

    if rasterizable:
        outcomes: List[dict] = []

        size = ocr_batch_size()
        for index, start in enumerate(range(0, len(rasterizable), size)):
            batch = rasterizable[start : start + size]
            jobs = []
            for j in batch:
                jobs.append(
                    {
                        "source": j["source"],
                        "spans": j["spans"],
                        "progress": j["progress"],
                        "index": j["index"],
                        "file_total": j["file_total"],
                    }
                )
            manifest = str(work / f"ocr-manifest-{index:03d}.json")
            write_manifest(manifest, jobs)

            try:
                outcomes.extend(
                    _run_stage(
                        ocr_python(),
                        "stage_ocr.py",
                        manifest,
                        str(work / f"ocr-result-{index:03d}.json"),
                        "ocr",
                    )
                )
            except StageError as e:
                log.error(
                    "OCR stage failed for %d of %d document(s): %s",
                    len(batch),
                    len(rasterizable),
                    e,
                )
                ocr_failures.extend(
                    _fail_all([j["source"] for j in batch], "ocr", str(e))
                )

        ocr_status = {o["source"]: o for o in outcomes}

    ready = []
    for j in rasterizable:
        if ocr_status.get(j["source"], {}).get("status") == "ok":
            ready.append(j)
    ready += text_only
    results = _run_nlp(ready, work)

    by_source = {r.source_path: r for r in results}
    failed_batches = {r.source_path: r for r in ocr_failures}

    ordered: List[DocumentResult] = []
    for job in plan:
        source = job["source"]
        if source in by_source:
            ordered.append(by_source[source])
            continue

        if source in failed_batches:
            ordered.append(failed_batches[source])
            continue

        outcome = ocr_status.get(source, {})
        ordered.append(
            DocumentResult(
                source_path=source,
                status="error",
                error=outcome.get("error") or "OCR stage returned no result",
                failed_stage="ocr",
                duration_seconds=float(outcome.get("duration_seconds", 0.0)),
            )
        )

    progress = progress_writer(progress_path, file_total=len(plan)).load()
    failures = [r for r in ordered if r.status != "ok"]
    if failures and len(failures) == len(ordered):
        progress.fail(failures[0].error or "de-identification failed")
    else:
        progress.finish()

    return ordered


def _describe_exit(returncode: int) -> str:
    if returncode >= 0:
        return f"exit {returncode}"
    try:
        name = signal.Signals(-returncode).name
    except ValueError:
        name = f"signal {-returncode}"
    if returncode == -9:
        return f"killed by {name}, most likely out of memory"
    return f"killed by {name}"


class _StageServer:
    def __init__(self, stage: str, interpreter: str, script: str, on_result, on_stop):
        self.stage = stage
        self.interpreter = interpreter
        self.script = script
        self.on_result = on_result
        self.on_stop = on_stop
        self.process = None
        self.lock = threading.Lock()

    def _start(self) -> None:
        command = [self.interpreter, str(OCR_ROOT / "scripts" / self.script), "--serve"]
        log.info("stage %s server: %s", self.stage, " ".join(command))
        try:
            self.process = subprocess.Popen(
                command,
                cwd=str(OCR_ROOT),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=os.environ.copy(),
            )
        except FileNotFoundError as e:
            raise StageError(
                f"{self.stage} stage interpreter not found at '{self.interpreter}'. "
                f"Set DEID_{self.stage.upper()}_PYTHON to the venv that has the "
                f"{self.stage} dependencies installed."
            ) from e
        threading.Thread(
            target=self._read, args=(self.process,), name=f"deid-{self.stage}", daemon=True
        ).start()

    def _read(self, process) -> None:
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self.on_result(json.loads(line))
            except Exception:
                log.exception("bad reply from the %s stage", self.stage)
        returncode = process.wait()
        self.on_stop(self.stage, process.pid, returncode)

    def send(self, job: Dict[str, Any]) -> int:
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self._start()
            try:
                self.process.stdin.write(json.dumps(job) + "\n")
                self.process.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                raise StageError(f"the {self.stage} stage is not running: {e}") from e
            return self.process.pid

    def close(self) -> None:
        with self.lock:
            process, self.process = self.process, None
        if process is None:
            return
        try:
            process.stdin.close()
        except OSError:
            pass
        process.wait()


class Service:
    def __init__(self, out, suffix: str, work: Path, keep_work: bool = False, problems=None):
        self.problems = problems or []
        self.out = out
        self.out_lock = threading.Lock()
        self.suffix = suffix
        self.work = work
        self.keep_work = keep_work
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Condition()
        self.ocr = _StageServer("ocr", ocr_python(), "stage_ocr.py", self._ocr_done, self._stopped)
        self.nlp = _StageServer("nlp", nlp_python(), "stage_nlp.py", self._nlp_done, self._stopped)

    def submit(self, request: Dict[str, Any]) -> None:
        job_id = str(request["id"])
        source = request["source"]
        output_root = Path(request["output_dir"]).expanduser()
        stem = Path(source).stem + self.suffix
        job = {
            "id": job_id,
            "source": source,
            "spans": str(self.work / f"{job_id}.spans.json"),
            "output_pdf": str(output_root / f"{stem}{output_extension(source)}"),
            "output_text": str(output_root / f"{stem}.txt"),
            "output_report": str(output_root / f"{stem}.report.json"),
            "progress": request.get("progress"),
        }
        stage = "ocr" if needs_ocr(source) else "nlp"
        with self.lock:
            self.jobs[job_id] = dict(job, stage=stage, pid=None)
        if self.problems:
            self._reply(job_id, error="; ".join(self.problems), stage="preflight")
            return
        try:
            output_root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._reply(job_id, error=str(e), stage=stage)
            return
        if stage == "ocr":
            self._send(self.ocr, job_id, {key: job[key] for key in ("id", "source", "spans", "progress")})
        else:
            self._send(self.nlp, job_id, job)

    def _send(self, server: "_StageServer", job_id: str, job: Dict[str, Any]) -> None:
        try:
            pid = server.send(job)
        except StageError as e:
            self._reply(job_id, error=str(e), stage=server.stage, retry=True)
            return
        with self.lock:
            if job_id in self.jobs:
                self.jobs[job_id]["pid"] = pid

    def _ocr_done(self, outcome: Dict[str, Any]) -> None:
        job_id = str(outcome.get("id"))
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return
            if outcome.get("status") == "ok":
                job["stage"] = "nlp"
                job["pid"] = None
        if job["stage"] != "nlp":
            self._reply(
                job_id,
                error=outcome.get("error") or "OCR stage returned no result",
                stage="ocr",
                retry=bool(outcome.get("retry")),
            )
            return
        self._send(self.nlp, job_id, {key: value for key, value in job.items() if key not in ("stage", "pid")})

    def _nlp_done(self, data: Dict[str, Any]) -> None:
        result = DocumentResult.from_dict(data)
        if result.status == "ok":
            self._reply(str(data.get("id")), output_pdf=result.output_pdf, method=result.method)
        else:
            self._reply(str(data.get("id")), error=result.error, stage=result.failed_stage or "nlp")

    def _stopped(self, stage: str, pid: int, returncode: int) -> None:
        with self.lock:
            lost = [
                job_id
                for job_id, job in self.jobs.items()
                if job["stage"] == stage and job["pid"] in (pid, None)
            ]
        if not lost:
            return
        log.error("the %s stage stopped (%s)", stage, _describe_exit(returncode))
        for job_id in lost:
            self._reply(
                job_id,
                error=f"the {stage} stage stopped ({_describe_exit(returncode)})",
                stage=stage,
                retry=True,
            )

    def _reply(self, job_id: str, output_pdf=None, method=None, error=None, stage=None, retry=False):
        with self.lock:
            job = self.jobs.pop(job_id, None)
            self.lock.notify_all()
        if job is None:
            return
        if not self.keep_work:
            Path(job["spans"]).unlink(missing_ok=True)
        progress = progress_writer(job.get("progress"), file_total=1).load()
        if error:
            progress.fail(error)
        else:
            progress.finish()
        reply = {
            "id": job_id,
            "source": job["source"],
            "status": "error" if error else "ok",
            "output_pdf": output_pdf,
            "method": method,
            "stage": stage,
            "error": error,
            "retry": retry,
        }
        with self.out_lock:
            self.out.write(json.dumps(reply) + "\n")
            self.out.flush()

    def wait(self) -> None:
        with self.lock:
            while self.jobs:
                self.lock.wait()

    def close(self) -> None:
        self.ocr.close()
        self.nlp.close()


def serve(lines, out, suffix: str = "_deid", work_dir: Optional[str] = None) -> int:
    problems = preflight()

    keep_work = _is_on("DEID_KEEP_WORK_DIR")
    if work_dir:
        work = Path(work_dir).expanduser()
        work.mkdir(parents=True, mode=0o700, exist_ok=True)
        owned = False
    else:
        work = Path(tempfile.mkdtemp(prefix="deid-serve-"))
        owned = True

    service = Service(out, suffix, work, keep_work, problems)
    try:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except ValueError:
                log.error("ignoring a request that is not JSON")
                continue
            service.submit(request)
        service.wait()
    finally:
        service.close()
        if owned and not keep_work:
            shutil.rmtree(work, ignore_errors=True)
    return 1 if problems else 0


def preflight() -> List[str]:
    problems: List[str] = []

    for name, interpreter in (("ocr", ocr_python()), ("nlp", nlp_python())):
        if not os.path.isfile(interpreter):
            problems.append(
                f"{name} interpreter not found at '{interpreter}' "
                f"(set DEID_{name.upper()}_PYTHON)"
            )
        elif not os.access(interpreter, os.X_OK):
            problems.append(f"{name} interpreter '{interpreter}' is not executable")

    for script in ("stage_ocr.py", "stage_nlp.py"):
        path = OCR_ROOT / "scripts" / script
        if not path.is_file():
            problems.append(f"missing stage script {path}")

    problems.extend(model_store.missing_models(load_config()))

    return problems


def describe_environment() -> dict:
    return {
        "orchestrator_python": sys.executable,
        "ocr_root": str(OCR_ROOT),
        "ocr_python": ocr_python(),
        "nlp_python": nlp_python(),
        "models": model_store.describe(load_config()),
    }
