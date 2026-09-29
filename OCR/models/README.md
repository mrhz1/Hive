# Models

All models used by the pipeline are stored here and loaded from disk.
Nothing is downloaded at run time (Cloudera AI blocks GitHub and Hugging
Face).

## Layout

Folder names match the model names in `deid/config.py`.

```
models/
├── paddle/
│   ├── PP-OCRv6_medium_det/
│   └── PP-OCRv6_medium_rec/
├── spacy/
│   └── en_core_web_sm/
└── transformers/
    └── StanfordAIMI/
        └── stanford-deidentifier-base/
```

About 570MB (paddle 133MB, spaCy 15MB, NER model 419MB).

`deid/model_store.py` also accepts `StanfordAIMI__stanford-deidentifier-base`
or just `stanford-deidentifier-base` for the transformers folder, and a
spaCy folder with one versioned subfolder inside.

## Download

On a machine with internet:

```bash
cd OCR
make models
```

or per stage:

```bash
.venv-ocr/bin/python scripts/stage_models.py --stage ocr
.venv-nlp/bin/python scripts/stage_models.py --stage nlp
```

Already downloaded models are skipped (`--force` to download again).

## Copy to Cloudera AI

```bash
tar czf models.tar.gz -C OCR models
# upload, then in a session:
tar xzf models.tar.gz -C /home/cdsw/OCR
cd /home/cdsw/OCR
make check-models
```

`make check-models` actually loads each model, so it also catches a
broken copy. If the models are somewhere else, set `DEID_MODELS_DIR`.

The folder isn't in git because of the size.

## Offline mode

`DEID_OFFLINE` is on by default. It sets `HF_HUB_OFFLINE` and
`TRANSFORMERS_OFFLINE`, and a missing model fails with the path it looked
in. Only turn it off on a machine that's downloading the models.
