"""The offline model store.

Cloudera AI blocks github and huggingface, so every weight is copied to
OCR/models/ and loaded by path. These tests cover the resolution rules
and, more importantly, the refusal: a model that is not staged must fail
immediately with the path it looked in, not fall back to a hub id and
fail on a blocked connection several hundred megabytes later.

They run under the API venv with neither ML stack installed, which is
also where the orchestrator's preflight runs.
"""
import sys
from pathlib import Path

import pytest

OCR_ROOT = Path(__file__).resolve().parent.parent / "OCR"
sys.path.insert(0, str(OCR_ROOT))

from deid import model_store  # noqa: E402
from deid.config import Config  # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    """An empty store somewhere writable, with offline on."""
    monkeypatch.setenv("DEID_MODELS_DIR", str(tmp_path))
    monkeypatch.setenv("DEID_OFFLINE", "1")
    return tmp_path


def _make(root: Path, relative: str, marker: str) -> Path:
    path = root / relative
    path.mkdir(parents=True, exist_ok=True)
    (path / marker).write_text("x")
    return path


def test_finds_a_model_by_its_exact_name(store):
    expected = _make(store, "paddle/PP-OCRv6_medium_det", "inference.json")
    assert model_store.find("paddle", "PP-OCRv6_medium_det") == expected


def test_a_directory_without_the_marker_file_does_not_count(store):
    """An empty folder is what a half-finished copy leaves behind, and
    treating it as present is how that becomes a crash inside paddle
    instead of a preflight failure."""
    (store / "paddle" / "PP-OCRv6_medium_det").mkdir(parents=True)
    assert model_store.find("paddle", "PP-OCRv6_medium_det") is None


def test_transformers_repo_id_keeps_its_org_name_shape(store):
    expected = _make(
        store, "transformers/StanfordAIMI/stanford-deidentifier-base", "config.json"
    )
    assert (
        model_store.find("transformers", "StanfordAIMI/stanford-deidentifier-base")
        == expected
    )


@pytest.mark.parametrize(
    "relative",
    [
        # The two plausible slips when a human copies the folder across.
        "transformers/StanfordAIMI__stanford-deidentifier-base",
        "transformers/stanford-deidentifier-base",
    ],
)
def test_off_canonical_transformers_layouts_still_resolve(store, relative):
    expected = _make(store, relative, "config.json")
    assert (
        model_store.find("transformers", "StanfordAIMI/stanford-deidentifier-base")
        == expected
    )


def test_spacy_wrapping_directory_resolves_to_the_inner_model(store):
    """`pip show en_core_web_sm` gives a package directory whose *inner*
    versioned directory holds config.cfg. Copying the outer one is the
    obvious thing to do, so it has to work."""
    expected = _make(store, "spacy/en_core_web_sm/en_core_web_sm-3.8.0", "config.cfg")
    assert model_store.find("spacy", "en_core_web_sm") == expected


def test_ambiguous_spacy_versions_are_not_guessed(store):
    _make(store, "spacy/en_core_web_sm/en_core_web_sm-3.7.0", "config.cfg")
    _make(store, "spacy/en_core_web_sm/en_core_web_sm-3.8.0", "config.cfg")
    assert model_store.find("spacy", "en_core_web_sm") is None


def test_offline_resolve_raises_and_names_where_it_looked(store):
    with pytest.raises(model_store.ModelNotFound) as excinfo:
        model_store.resolve("spacy", "en_core_web_sm")

    message = str(excinfo.value)
    assert str(store / "spacy" / "en_core_web_sm") in message
    # The message has to be actionable in a job log, where it is all
    # anyone gets.
    assert "stage_models.py" in message


def test_online_resolve_falls_back_to_the_hub_id(store, monkeypatch):
    """DEID_OFFLINE=0 is how a laptop with egress works before anything
    has been staged -- the loaders take a name or a path in the same
    argument, so nothing branches."""
    monkeypatch.setenv("DEID_OFFLINE", "0")
    assert model_store.resolve("spacy", "en_core_web_sm") == "en_core_web_sm"


def test_missing_models_reports_every_gap(store):
    problems = model_store.missing_models(Config())
    assert len(problems) == 4
    assert any("en_core_web_sm" in p for p in problems)


def test_missing_models_is_silent_when_downloading_is_allowed(store, monkeypatch):
    monkeypatch.setenv("DEID_OFFLINE", "0")
    assert model_store.missing_models(Config()) == []


def test_a_fully_staged_store_has_no_problems(store):
    config = Config()
    _make(store, f"paddle/{config.det_model}", "inference.json")
    _make(store, f"paddle/{config.rec_model}", "inference.json")
    _make(store, f"spacy/{config.spacy_model}", "config.cfg")
    _make(store, f"transformers/{config.transformers_model}", "config.json")

    assert model_store.missing_models(config) == []


def test_offline_env_is_applied_before_transformers_would_read_it(monkeypatch):
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DEID_OFFLINE", "1")

    model_store.apply_offline_env()

    import os

    assert os.environ["HF_HUB_OFFLINE"] == "1"
    assert os.environ["TRANSFORMERS_OFFLINE"] == "1"


def test_offline_env_leaves_a_deliberate_override_alone(monkeypatch):
    """Someone debugging a staging problem has set this on purpose."""
    monkeypatch.setenv("DEID_OFFLINE", "1")
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")

    model_store.apply_offline_env()

    import os

    assert os.environ["HF_HUB_OFFLINE"] == "0"


def test_offline_env_does_nothing_when_downloading_is_allowed(monkeypatch):
    monkeypatch.setenv("DEID_OFFLINE", "0")
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)

    model_store.apply_offline_env()

    import os

    assert "HF_HUB_OFFLINE" not in os.environ
