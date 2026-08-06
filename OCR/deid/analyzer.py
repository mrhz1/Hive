"""Presidio analyzer built on a transformers NLP engine.

spaCy (en_core_web_sm) does tokenization/lemmatization; NER comes from
StanfordAIMI/stanford-deidentifier-base. Presidio's built-in pattern and
checksum recognizers (SSN, credit card, IBAN, email, ...) run alongside
the NER model, and deid/recognizers.py adds address/ZIP/MRN/age coverage
the NER model lacks.

This module is the presidio half of the split: it must only ever be
imported under the NLP virtualenv, and nothing importable from the OCR
virtualenv may import it. See deid/pipeline.py.
"""
import logging
from typing import List

from deid import model_store
from deid.config import MODEL_TO_PRESIDIO_ENTITY, Config
from deid.recognizers import build_custom_recognizers
from deid.spans import PiiSpan

log = logging.getLogger(__name__)

__all__ = ["PiiSpan", "analyze_text", "build_analyzer", "merge_overlapping"]


def build_analyzer(config: Config):
    """Construct the Presidio AnalyzerEngine.

    Import-heavy, so it is called once per job run and reused.
    """
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import (
        NerModelConfiguration,
        TransformersNlpEngine,
    )

    # Both of these become filesystem paths under DEID_OFFLINE (the
    # default), which is what stops Presidio downloading. It matters for
    # each in a different way:
    #
    #   spaCy      -- SpacyNlpEngine._download_spacy_model_if_needed()
    #                 skips the download when the name is a path that
    #                 exists, so a path is the only offline-safe form;
    #                 a *package* name would work too but only if the
    #                 wheel was pip-installed, and that wheel comes from
    #                 github, which is blocked.
    #   transformers -- the name is handed to the hf_token_pipe, and
    #                 from_pretrained() treats a local directory as the
    #                 model, no hub lookup.
    spacy_model = model_store.resolve(model_store.SPACY_DIR, config.spacy_model)
    transformers_model = model_store.resolve(
        model_store.TRANSFORMERS_DIR, config.transformers_model
    )

    log.info(
        "building analyzer spacy=%s transformers=%s",
        spacy_model,
        transformers_model,
    )

    models = [
        {
            "lang_code": "en",
            "model_name": {
                "spacy": spacy_model,
                "transformers": transformers_model,
            },
        }
    ]

    ner_config = NerModelConfiguration(
        model_to_presidio_entity_mapping=MODEL_TO_PRESIDIO_ENTITY,
        labels_to_ignore=["O"],
        # "max" keeps the highest-scoring label across sub-tokens;
        # "expand" grows a span to whole words, which matters because a
        # half-redacted name still leaks the name.
        aggregation_strategy="max",
        alignment_mode="expand",
        # Sliding-window overlap so entities straddling the model's token
        # limit are not cut in half on long pages.
        stride=16,
        low_confidence_score_multiplier=0.4,
        low_score_entity_names=["ID"],
    )

    nlp_engine = TransformersNlpEngine(
        models=models, ner_model_configuration=ner_config
    )

    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])

    for recognizer in build_custom_recognizers():
        analyzer.registry.add_recognizer(recognizer)
        log.debug("registered custom recognizer %s", recognizer.name)

    return analyzer


def analyze_text(analyzer, text: str, config: Config) -> List[PiiSpan]:
    """Run detection over one page's text."""
    if not text.strip():
        return []

    try:
        results = analyzer.analyze(
            text=text,
            language="en",
            entities=config.entities or None,
            score_threshold=config.score_threshold,
        )
    except Exception:
        log.exception("presidio analysis failed")
        raise

    spans = [
        PiiSpan(
            entity_type=r.entity_type,
            start=r.start,
            end=r.end,
            score=float(r.score),
        )
        for r in results
    ]
    return merge_overlapping(spans)


def merge_overlapping(spans: List[PiiSpan]) -> List[PiiSpan]:
    """Collapse overlapping detections into disjoint spans.

    Recognizers overlap constantly -- the NER model tags "Springfield, IL"
    as ORGANIZATION while the ZIP recognizer tags "IL 62704", and both
    cover the same characters. Leaving them overlapping corrupts the
    redacted text (replacing one span mangles the tag already inserted by
    another) and produces duplicate redaction boxes.

    The merged span takes the union of the ranges and the entity type of
    the highest-scoring member, which keeps the most confident label.
    """
    if not spans:
        return []

    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    merged: List[PiiSpan] = [ordered[0]]

    for span in ordered[1:]:
        current = merged[-1]
        if span.start < current.end:  # overlap
            if span.score > current.score:
                current.entity_type = span.entity_type
                current.score = span.score
            current.end = max(current.end, span.end)
        else:
            merged.append(span)

    return merged
