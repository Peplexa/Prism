"""
BillSum dataset loader.

The BillSum dataset contains US Congressional and California state bills
paired with professional reference summaries.
Source: https://huggingface.co/datasets/FiscalNote/billsum
"""
from __future__ import annotations

from typing import Any, Iterator

from django.conf import settings

from .base import DatasetLoader


class BillSumLoader(DatasetLoader):
    """Loads BillSum Congressional bills with summaries via HuggingFace datasets."""

    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir or settings.BILLSUM_CACHE_DIR

    @property
    def name(self) -> str:
        return "billsum"

    @property
    def description(self) -> str:
        return "US Congressional and CA state bills with professional summaries"

    def get_available_splits(self) -> list[str]:
        return ["train", "test", "ca_test"]

    def load(self, split: str = "train", limit: int | None = None) -> Iterator[dict[str, Any]]:
        """Load documents from BillSum dataset via HuggingFace."""
        from datasets import load_dataset

        # Load from HuggingFace
        dataset = load_dataset(
            "FiscalNote/billsum",
            split=split,
            cache_dir=str(self.cache_dir),
        )

        count = 0
        for i, entry in enumerate(dataset):
            if limit and count >= limit:
                break

            bill_text = entry.get("text", "")
            summary = entry.get("summary", "")
            title = entry.get("title", "")

            # Skip entries with missing content
            if not bill_text or not summary:
                continue

            yield {
                "external_id": f"{split}_{i}",
                "primary_text": bill_text,
                "reference_content": {"summary": summary},
                "title": title,
                "metadata": {
                    "split": split,
                    "text_length": len(bill_text),
                    "summary_length": len(summary),
                },
            }
            count += 1

    def extract_ground_truth(self, document_data: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract ground truth facts from the professional summary.

        For BillSum, we treat the professional summary as containing
        the key facts that should be extracted from the bill.
        We split the summary into sentences as atomic facts.
        """
        summary = document_data["reference_content"].get("summary", "")
        if not summary:
            return []

        facts = []

        # Split summary into sentences
        # Use simple sentence splitting (can be improved with spaCy)
        sentences = self._split_into_sentences(summary)

        for i, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence or len(sentence) < 10:
                continue

            # Classify the sentence type based on content
            fact_type = self._classify_sentence(sentence)

            facts.append({
                "fact_text": sentence,
                "fact_type": fact_type,
                "confidence": 1.0,
                "metadata": {
                    "sentence_index": i,
                    "source": "summary",
                },
            })

        return facts

    def _split_into_sentences(self, text: str) -> list[str]:
        """Split text into sentences."""
        import re

        # Handle common abbreviations to avoid false splits
        text = re.sub(r"\b(Mr|Mrs|Ms|Dr|Jr|Sr|Rep|Sen|Gov)\.", r"\1<DOT>", text)
        text = re.sub(r"\b(U\.S\.|U\.S\.C\.)", lambda m: m.group().replace(".", "<DOT>"), text)

        # Split on sentence-ending punctuation
        sentences = re.split(r"(?<=[.!?])\s+", text)

        # Restore dots
        sentences = [s.replace("<DOT>", ".") for s in sentences]

        return sentences

    def _classify_sentence(self, sentence: str) -> str:
        """Classify sentence into a category based on content patterns."""
        sentence_lower = sentence.lower()

        if any(
            word in sentence_lower
            for word in ["amend", "strike", "insert", "delete", "redesignate"]
        ):
            return "amendment"

        if any(
            word in sentence_lower
            for word in ["appropriate", "authoriz", "million", "billion", "fund"]
        ):
            return "appropriation"

        if any(word in sentence_lower for word in ["define", "means", "referred to as"]):
            return "definition"

        if any(
            word in sentence_lower
            for word in ["require", "shall", "must", "prohibit", "mandate"]
        ):
            return "requirement"

        if any(
            word in sentence_lower
            for word in ["effective", "take effect", "enact", "upon enactment"]
        ):
            return "effective_date"

        return "provision"
