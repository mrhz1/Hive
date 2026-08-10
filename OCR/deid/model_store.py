"""The local model store: weights on disk, never off the network."""
import os
from pathlib import Path
from typing import Dict, List, Optional

OCR_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_MODELS_DIR = OCR_ROOT / "models"

PADDLE_DIR = "paddle"
SPACY_DIR = "spacy"
TRANSFORMERS_DIR = "transformers"

MARKERS: Dict[str, tuple] = {
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
    """Where a model called `name` could legitimately live."""
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
    """What to hand the loader: a local path, or the hub id if allowed."""
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
    """Bolt the doors on the HuggingFace stack, before it is imported."""
    if not offline():
        return

    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_DATASETS_OFFLINE"):
        os.environ.setdefault(name, "1")

    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def required_models(config) -> List[tuple]:
    """(kind, name) for every model a full run needs."""
    return [
        (PADDLE_DIR, config.det_model),
        (PADDLE_DIR, config.rec_model),
        (SPACY_DIR, config.spacy_model),
        (TRANSFORMERS_DIR, config.transformers_model),
    ]


def missing_models(config) -> List[str]:
    """Human-readable descriptions of what preflight could not find."""
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
    """What resolved to what -- worth having in a job log when a deployment loads the wrong weights."""
    return {
        "models_dir": str(models_dir()),
        "offline": offline(),
        "resolved": {
            f"{kind}:{name}": str(find(kind, name) or "")
            for kind, name in required_models(config)
        },
    }
