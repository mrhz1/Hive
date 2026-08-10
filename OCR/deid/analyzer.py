"""Presidio analyzer built on a transformers NLP engine."""
import logging
from typing import List

from deid import model_store
from deid.config import MODEL_TO_PRESIDIO_ENTITY, Config
from deid.recognizers import build_custom_recognizers
from deid.spans import PiiSpan

log = logging.getLogger(__name__)

__all__ = ["PiiSpan", "analyze_text", "build_analyzer", "merge_overlapping"]


def build_analyzer(config: Config):
    """Construct the Presidio AnalyzerEngine."""
    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import (
        NerModelConfiguration,
        TransformersNlpEngine,
    )

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
        aggregation_strategy="max",
        alignment_mode="expand",
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
    """Collapse overlapping detections into disjoint spans."""
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
