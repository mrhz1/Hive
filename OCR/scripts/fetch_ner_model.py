"""Resilient download of the NER model.

Kept separate from download_models.py because this is the one large
artifact (~440MB pytorch_model.bin) and the one most likely to fail on a
slow link. huggingface_hub resumes partial blobs, so re-running continues
rather than restarting.

allow_patterns keeps TF/Flax/ONNX copies of the same weights out of the
download -- the repo carries several formats and we only need PyTorch.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deid.config import load_config  # noqa: E402

ALLOW = [
    "config.json",
    "pytorch_model.bin",
    "model.safetensors",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "special_tokens_map.json",
]

MAX_ATTEMPTS = 8


def main() -> int:
    from huggingface_hub import snapshot_download

    model = load_config().transformers_model
    print(f"fetching {model}")

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            path = snapshot_download(
                repo_id=model,
                allow_patterns=ALLOW,
                # Single worker is slower in theory but far more stable on
                # a flaky link than parallel range requests.
                max_workers=1,
            )
            print(f"OK -> {path}")
            return 0
        except Exception as exc:
            print(f"attempt {attempt}/{MAX_ATTEMPTS} failed: {exc}")
            if attempt == MAX_ATTEMPTS:
                print("giving up")
                return 1
            time.sleep(min(30, 5 * attempt))
    return 1


if __name__ == "__main__":
    sys.exit(main())
