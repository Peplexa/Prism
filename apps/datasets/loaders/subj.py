"""
SUBJ dataset loader.

The SUBJ dataset (Pang & Lee, 2004) contains 10,000 sentences labeled as
objective or subjective, sourced from Rotten Tomatoes reviews (subjective)
and IMDB plot summaries (objective).
Source: https://huggingface.co/datasets/SetFit/subj
"""
from __future__ import annotations

from typing import Any, Iterator

from django.conf import settings

from .base import DatasetLoader


class SUBJLoader(DatasetLoader):
    """Loads SUBJ subjectivity dataset via HuggingFace datasets."""

    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir or getattr(
            settings, 'SUBJ_CACHE_DIR', settings.BASE_DIR / 'data' / 'subj'
        )

    @property
    def name(self) -> str:
        return "subj"

    @property
    def description(self) -> str:
        return "Sentence-level subjectivity dataset (Pang & Lee 2004): 10k sentences labeled objective/subjective"

    def get_available_splits(self) -> list[str]:
        return ["train", "test"]

    def load(self, split: str = "train", limit: int | None = None) -> Iterator[dict[str, Any]]:
        """Load sentences from SUBJ dataset via HuggingFace."""
        from datasets import load_dataset

        dataset = load_dataset(
            "SetFit/subj",
            split=split,
            cache_dir=str(self.cache_dir),
        )

        count = 0
        for i, entry in enumerate(dataset):
            if limit and count >= limit:
                break

            text = entry.get("text", "")
            if not text:
                continue

            label = entry.get("label", 0)
            label_text = entry.get("label_text", "objective" if label == 0 else "subjective")

            yield {
                "external_id": f"{split}_{i}",
                "primary_text": text,
                "reference_content": {
                    "label": label,
                    "label_text": label_text,
                },
                "title": "",
                "metadata": {
                    "split": split,
                    "text_length": len(text),
                },
            }
            count += 1

    def extract_ground_truth(self, document_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract ground truth label from reference content."""
        ref = document_data.get("reference_content", {})
        label = ref.get("label", 0)
        label_text = ref.get("label_text", "objective")

        return [{
            "fact_text": label_text,
            "fact_type": "subjectivity",
            "confidence": 1.0,
            "metadata": {
                "label": label,
                "label_text": label_text,
            },
        }]
