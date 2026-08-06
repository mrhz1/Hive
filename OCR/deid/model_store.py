"""The local model store: weights on disk, never off the network.

Cloudera AI blocks github.com and huggingface.co, so nothing here may
resolve a model by downloading it. Every weight is copied into
`OCR/models/` ahead of time (see scripts/stage_models.py) and loaded from
there by path.

    OCR/models/
      paddle/PP-OCRv6_medium_det/           inference.json/.pdiparams/.yml
      paddle/PP-OCRv6_medium_rec/
      spacy/en_core_web_sm/                 a directory holding config.cfg
      transformers/StanfordAIMI/stanford-deidentifier-base/

The directory names are the model identifiers verbatim -- the same
strings `deid/config.py` pins -- so changing a model means dropping in a
folder with the matching name, not editing this file. A transformers repo
id keeps its `org/name` shape as a nested directory for the same reason.

This module is stdlib only. Both stages import it (they resolve
different models) and so does the orchestrator's preflight, which runs
under a python with nothing installed at all.

## Offline is the default

`DEID_OFFLINE` defaults to on, and on means two things:

  * `apply_offline_env()` sets the HuggingFace offline switches before
    transformers is imported, so a stray `from_pretrained("org/name")`
    anywhere in the dependency tree fails fast instead of hanging on a
    blocked connection until the job times out;
  * a model missing from the store raises `ModelNotFound` naming the
    directory it looked in, rather than silently falling back to the hub
    id and failing 400MB later.

Set `DEID_OFFLINE=0` on a machine with egress -- that is what the staging
script does, and it is the only supported way to download anything.
"""
import os
from pathlib import Path
from typing import Dict, List, Optional

# The OCR package root, so the default store location does not depend on
# the process's working directory.
OCR_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_MODELS_DIR = OCR_ROOT / "models"

# Subdirectory per framework. Kept apart because the three have entirely
# different on-disk shapes and a flat directory would make "is this
# model present?" ambiguous.
PADDLE_DIR = "paddle"
SPACY_DIR = "spacy"
TRANSFORMERS_DIR = "transformers"

# A file whose presence means "this directory really is a model of this
# kind", not just an empty folder left by a half-finished copy. Checking
# for the marker is what turns a botched transfer into a clear preflight
# failure instead of a stack trace inside paddle.
MARKERS: Dict[str, tuple] = {
    # PaddleX inference dirs: .json is the PIR program (paddle 3.x),
    # .pdmodel the legacy one. Either counts.
    PADDLE_DIR: ("inference.json", "inference.pdmodel"),
    SPACY_DIR: ("config.cfg",),
    TRANSFORMERS_DIR: ("config.json",),
}


class ModelNotFound(RuntimeError):
    """A model is not in the local store and we are not allowed to fetch it."""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def offline() -> bool:
    return _env_bool("DEID_OFFLINE", True)


def models_dir() -> Path:
    raw = os.environ.get("DEID_MODELS_DIR")
    return Path(raw).expanduser().resolve() if raw else DEFAULT_MODELS_DIR


def _has_marker(path: Path, kind: str) -> bool:
    return any((path / marker).is_file() for marker in MARKERS[kind])


def _candidates(kind: str, name: str) -> List[Path]:
    """Where a model called `name` could legitimately live.

    More than one, because the transfer to Cloudera is a human copying
    directories and the plausible mistakes are worth absorbing:

      transformers/StanfordAIMI/stanford-deidentifier-base   canonical
      transformers/StanfordAIMI__stanford-deidentifier-base  flattened
      transformers/stanford-deidentifier-base                basename only

    A spaCy model gets one extra: the pip package directory contains a
    versioned subdirectory (`en_core_web_sm/en_core_web_sm-3.8.0/`) and
    it is the *inner* one that holds config.cfg, so copying the outer
    one -- the obvious thing to do -- has to keep working.
    """
    root = models_dir() / kind
    name = name.strip().strip("/")
    paths = [root / name]

    if "/" in name:
        paths.append(root / name.replace("/", "__"))
        paths.append(root / name.rsplit("/", 1)[1])

    resolved: List[Path] = []
    for path in paths:
        resolved.append(path)
        if kind == SPACY_DIR and path.is_dir() and not _has_marker(path, kind):
            # Exactly one versioned subdirectory is the pip layout; more
            # than one is ambiguous and we would rather say "not found"
            # than guess which version was meant.
            inner = [p for p in sorted(path.iterdir()) if _has_marker(p, kind)]
            if len(inner) == 1:
                resolved.append(inner[0])

    return resolved


def find(kind: str, name: str) -> Optional[Path]:
    """The local directory for `name`, or None if it is not staged."""
    for candidate in _candidates(kind, name):
        if candidate.is_dir() and _has_marker(candidate, kind):
            return candidate
    return None


def resolve(kind: str, name: str) -> str:
    """What to hand the loader: a local path, or the hub id if allowed.

    Returning the hub id under `DEID_OFFLINE=0` is what keeps a
    developer's machine working before anything has been staged --
    paddle/transformers/spaCy all accept either form in the same
    argument, so the loaders do not branch.
    """
    local = find(kind, name)
    if local is not None:
        return str(local)

    if offline():
        raise ModelNotFound(
            f"{kind} model '{name}' is not in the local model store. "
            f"Looked in: {', '.join(str(p) for p in _candidates(kind, name))}. "
            f"Stage it with scripts/stage_models.py on a machine with "
            f"network access and copy {models_dir()} across, or set "
            f"DEID_OFFLINE=0 to allow downloading."
        )
    return name


def apply_offline_env() -> None:
    """Bolt the doors on the HuggingFace stack, before it is imported.

    Only meaningful if this runs before `import transformers`: the
    library reads these into module-level constants at import time, so
    setting them afterwards does nothing. Both stage entrypoints call it
    as their first action for that reason.

    Existing values are left alone -- an operator who has deliberately
    set HF_HUB_OFFLINE=0 to debug a staging problem should not have it
    silently overridden.
    """
    if not offline():
        return

    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ.setdefault(name, "1")

    # PaddleX has no offline switch: it resolves an unknown model name by
    # downloading it, and before doing so probes huggingface/modelscope/
    # aistudio/BOS for reachability. On a network that drops rather than
    # refuses, that probe is a multi-minute stall before the real error.
    # Passing explicit model dirs means we never reach the download path
    # at all -- this only makes the failure fast if we ever do.
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def required_models(config) -> List[tuple]:
    """(kind, name) for every model a full run needs.

    Takes the Config rather than reading env vars again so preflight can
    never disagree with what the stages will actually load.
    """
    return [
        (PADDLE_DIR, config.det_model),
        (PADDLE_DIR, config.rec_model),
        (SPACY_DIR, config.spacy_model),
        (TRANSFORMERS_DIR, config.transformers_model),
    ]


def missing_models(config) -> List[str]:
    """Human-readable descriptions of what preflight could not find.

    Empty when offline is disabled: the models are then allowed to arrive
    by download, so their absence is not yet a problem.
    """
    if not offline():
        return []

    problems = []
    for kind, name in required_models(config):
        if find(kind, name) is None:
            problems.append(
                f"{kind} model '{name}' missing from the model store "
                f"(expected {models_dir() / kind / name})"
            )
    return problems


def describe(config) -> dict:
    """What resolved to what -- worth having in a job log when a
    deployment loads the wrong weights."""
    return {
        "models_dir": str(models_dir()),
        "offline": offline(),
        "resolved": {
            f"{kind}:{name}": str(find(kind, name) or "")
            for kind, name in required_models(config)
        },
    }
