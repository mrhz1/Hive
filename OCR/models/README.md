# The local model store

Every weight the de-identification pipeline loads lives in this
directory, and it is loaded **by path**. Nothing is downloaded at job
time.

That is not an optimisation. The Cloudera AI environment this deploys to
blocks `github.com` and `huggingface.co`, which is where all four models
normally come from. pip packages install fine; model weights do not
arrive over pip.

## Layout

Directory names are the model identifiers verbatim — the same strings
pinned in `deid/config.py`. Changing a model means dropping in a folder
with the matching name, not editing code.

```
models/
├── paddle/
│   ├── PP-OCRv6_medium_det/                    inference.json + .pdiparams + .yml
│   └── PP-OCRv6_medium_rec/
├── spacy/
│   └── en_core_web_sm/                         config.cfg + the pipe directories
└── transformers/
    └── StanfordAIMI/                           the repo id keeps its org/name shape
        └── stanford-deidentifier-base/         config.json + pytorch_model.bin + tokenizer
```

Roughly 570MB in total: 133MB paddle, 15MB spaCy, 419MB the NER model.

`deid/model_store.py` resolves these. It also accepts two off-canonical
spellings of the transformers path (`StanfordAIMI__stanford-deidentifier-base`
and the bare `stanford-deidentifier-base`) and, for spaCy, a wrapping
directory containing a single versioned subdirectory — because the
transfer is a human copying folders and those are the plausible slips.

## Filling it

On a machine **with** network access:

```bash
cd OCR
make models          # both stages; ~570MB, a few minutes
```

or one stage at a time:

```bash
.venv-ocr/bin/python scripts/stage_models.py --stage ocr
.venv-nlp/bin/python scripts/stage_models.py --stage nlp
```

Two runs because the two stages have separate virtualenvs and each can
only download what it can import. Re-running skips whatever is already
staged; `--force` re-downloads.

The HuggingFace cache stores files as symlinks into a blob directory, so
the staging script resolves them — this directory is real files only, and
copying it anywhere is enough.

## Moving it to Cloudera AI

```bash
tar czf models.tar.gz -C OCR models          # ~500MB compressed
# upload models.tar.gz to the CML project, then in a session:
tar xzf models.tar.gz -C /home/cdsw/OCR
```

Then, **on the Cloudera node**, confirm the transfer:

```bash
cd /home/cdsw/OCR
make check-models    # loads every model with the network switched off
```

`make check-models` is the check that matters. `run_deid.py --preflight`
verifies the directories exist, which catches an incomplete copy but not
a corrupt one — a truncated `pytorch_model.bin` passes the directory
check and fails several minutes into the first real job.

If the store lives somewhere other than `OCR/models`, point
`DEID_MODELS_DIR` at it (a read-only mount is fine; nothing writes here
at run time).

## Why this is not in git

~570MB of binaries would be in every clone of this repo forever, and git
is not the transport to Cloudera anyway — the upload is. `.gitignore`
keeps the weights out and this file in. Use git-lfs or an artifact
store if the transfer needs to be automated.

## Offline is enforced, not assumed

`DEID_OFFLINE` defaults to on. It sets `HF_HUB_OFFLINE` /
`TRANSFORMERS_OFFLINE` before transformers is imported, and makes a
missing model raise immediately — naming the directory it looked in —
rather than falling back to a hub id and failing on a blocked connection
several hundred megabytes later.

Set `DEID_OFFLINE=0` only on a machine with egress. The staging script
sets it for its own process; nothing else should.
