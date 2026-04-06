from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterator


class DatasetLoader(ABC):
    """Abstract base class for dataset loaders."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the dataset name."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Return a description of the dataset."""
        pass

    @abstractmethod
    def load(self, split: str = "train", limit: int | None = None) -> Iterator[dict[str, Any]]:
        """
        Yield documents from the dataset.

        Each document should have:
        - external_id: Unique identifier within the dataset
        - primary_text: Main text content (summary for Rotowire, bill text for BillSum)
        - reference_content: Ground truth data (box scores, professional summary)
        - title: Optional document title
        - metadata: Additional metadata
        """
        pass

    @abstractmethod
    def extract_ground_truth(self, document_data: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Extract ground truth facts from document reference content.

        Returns list of dicts with:
        - fact_text: The atomic fact
        - fact_type: Category of the fact
        - confidence: Confidence score (default 1.0)
        - metadata: Additional metadata
        """
        pass

    def get_available_splits(self) -> list[str]:
        """Return available data splits."""
        return ["train", "valid", "test"]
