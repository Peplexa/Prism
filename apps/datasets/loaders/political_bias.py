"""
PoliticalBias_AllSides_Txt dataset loader.

~17k news articles labeled left/center/right by AllSides.com editors.
Source: https://huggingface.co/datasets/valurank/PoliticalBias_AllSides_Txt

The dataset is a zip file with three folders: Left Data/, Center Data/, Right Data/.
HuggingFace's load_dataset loses the folder-based labels, so we read the zip directly.
"""
from __future__ import annotations

import zipfile
from typing import Any, Iterator

from django.conf import settings

from .base import DatasetLoader

# Map folder names to canonical labels
FOLDER_LABEL_MAP = {
    "Left Data": "left",
    "Center Data": "center",
    "Right Data": "right",
}


class PoliticalBiasLoader(DatasetLoader):
    """Loads PoliticalBias AllSides dataset from HuggingFace zip."""

    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir or getattr(
            settings, 'POLITICAL_BIAS_CACHE_DIR',
            settings.BASE_DIR / 'data' / 'political_bias',
        )

    @property
    def name(self) -> str:
        return "political_bias"

    @property
    def description(self) -> str:
        return "AllSides news articles labeled left/center/right (~17k articles)"

    def get_available_splits(self) -> list[str]:
        return ["train"]

    def _get_zip_path(self):
        """Download zip via huggingface_hub and return local path."""
        from huggingface_hub import hf_hub_download

        return hf_hub_download(
            repo_id="valurank/PoliticalBias_AllSides_Txt",
            filename="AllSides.zip",
            repo_type="dataset",
            cache_dir=str(self.cache_dir),
        )

    def load(self, split: str = "train", limit: int | None = None) -> Iterator[dict[str, Any]]:
        """Load articles from PoliticalBias zip with folder-based labels.

        Articles are grouped by folder in the zip (Center, Left, Right).
        We round-robin across labels so limited samples are balanced.
        """
        zip_path = self._get_zip_path()

        # Group file entries by label
        entries_by_label: dict[str, list[tuple[str, str]]] = {
            "left": [], "center": [], "right": [],
        }

        with zipfile.ZipFile(zip_path, "r") as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                parts = name.split("/")
                if len(parts) < 3:
                    continue
                folder = parts[1]
                label_text = FOLDER_LABEL_MAP.get(folder)
                if label_text is not None:
                    entries_by_label[label_text].append((name, folder))

            # Round-robin across labels for balanced sampling
            iterators = {k: iter(v) for k, v in entries_by_label.items()}
            count = 0
            active_labels = list(iterators.keys())

            while active_labels:
                if limit and count >= limit:
                    break

                exhausted = []
                for label in active_labels:
                    if limit and count >= limit:
                        break
                    try:
                        name, folder = next(iterators[label])
                    except StopIteration:
                        exhausted.append(label)
                        continue

                    try:
                        text = zf.read(name).decode("utf-8", errors="replace").strip()
                    except Exception:
                        continue

                    if not text or len(text.split()) < 20:
                        continue

                    yield {
                        "external_id": f"{split}_{count}",
                        "primary_text": text,
                        "reference_content": {
                            "label": label,
                            "label_text": label,
                        },
                        "title": "",
                        "metadata": {
                            "split": split,
                            "folder": folder,
                            "filename": name.split("/")[-1],
                            "text_length": len(text),
                            "word_count": len(text.split()),
                        },
                    }
                    count += 1

                for label in exhausted:
                    active_labels.remove(label)

    def extract_ground_truth(self, document_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract ground truth label from reference content."""
        ref = document_data.get("reference_content", {})
        label_text = ref.get("label_text", "unknown")

        return [{
            "fact_text": label_text,
            "fact_type": "political_leaning",
            "confidence": 1.0,
            "metadata": {
                "label_text": label_text,
            },
        }]
