"""
Nugget matching service.

Matches extracted nuggets against ground truth facts using semantic similarity.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from django.conf import settings
from scipy.optimize import linear_sum_assignment

logger = logging.getLogger(__name__)


@dataclass
class MatchingResult:
    """Result of matching extracted nuggets to ground truth."""

    matches: list[tuple[int, int, float]]  # (extracted_idx, truth_idx, similarity)
    unmatched_extracted: list[int]  # False positives
    unmatched_truth: list[int]  # False negatives (omissions)


class SemanticMatcher:
    """Matches extracted nuggets to ground truth using semantic similarity."""

    _model_cache: dict = {}

    def __init__(
        self,
        model_name: str | None = None,
        threshold: float | None = None,
    ):
        self.model_name = model_name or settings.SEMANTIC_MODEL
        self.threshold = threshold or settings.DEFAULT_SIMILARITY_THRESHOLD
        self._model = self._get_model(self.model_name)

    @classmethod
    def _get_model(cls, model_name: str):
        """Get or create cached sentence transformer model."""
        if model_name not in cls._model_cache:
            # Block torchvision (incompatible with torch 2.10.0)
            import importlib.util
            _orig = importlib.util.find_spec
            def _no_tv(name, *a, **kw):
                if name == 'torchvision' or name.startswith('torchvision.'):
                    return None
                return _orig(name, *a, **kw)
            importlib.util.find_spec = _no_tv
            try:
                from sentence_transformers import SentenceTransformer
            finally:
                importlib.util.find_spec = _orig
            logger.info(f"Loading sentence transformer: {model_name}")
            cls._model_cache[model_name] = SentenceTransformer(model_name)
        return cls._model_cache[model_name]

    def match(
        self,
        extracted_nuggets: list[str],
        ground_truth_facts: list[str],
    ) -> MatchingResult:
        """
        Match extracted nuggets to ground truth facts.

        Uses optimal assignment (Hungarian algorithm) to find best matches,
        then filters by similarity threshold.

        Args:
            extracted_nuggets: List of extracted nugget texts
            ground_truth_facts: List of ground truth fact texts

        Returns:
            MatchingResult with matches and unmatched indices
        """
        if not extracted_nuggets and not ground_truth_facts:
            return MatchingResult(matches=[], unmatched_extracted=[], unmatched_truth=[])

        if not extracted_nuggets:
            return MatchingResult(
                matches=[],
                unmatched_extracted=[],
                unmatched_truth=list(range(len(ground_truth_facts))),
            )

        if not ground_truth_facts:
            return MatchingResult(
                matches=[],
                unmatched_extracted=list(range(len(extracted_nuggets))),
                unmatched_truth=[],
            )

        # Compute similarity matrix
        similarity_matrix = self._compute_similarity_matrix(
            extracted_nuggets, ground_truth_facts
        )

        # Find optimal assignment
        matches, unmatched_extracted, unmatched_truth = self._optimal_assignment(
            similarity_matrix
        )

        return MatchingResult(
            matches=matches,
            unmatched_extracted=unmatched_extracted,
            unmatched_truth=unmatched_truth,
        )

    def _compute_similarity_matrix(
        self,
        extracted: list[str],
        truth: list[str],
    ) -> np.ndarray:
        """Compute cosine similarity matrix between extracted and truth."""
        # Encode all texts
        extracted_embeddings = self._model.encode(extracted, convert_to_numpy=True)
        truth_embeddings = self._model.encode(truth, convert_to_numpy=True)

        # Normalize for cosine similarity
        extracted_norm = extracted_embeddings / np.linalg.norm(
            extracted_embeddings, axis=1, keepdims=True
        )
        truth_norm = truth_embeddings / np.linalg.norm(
            truth_embeddings, axis=1, keepdims=True
        )

        # Compute similarity matrix
        similarity = np.dot(extracted_norm, truth_norm.T)

        return similarity

    def _optimal_assignment(
        self,
        similarity_matrix: np.ndarray,
    ) -> tuple[list[tuple[int, int, float]], list[int], list[int]]:
        """
        Find optimal assignment using Hungarian algorithm.

        Returns matches above threshold and unmatched indices.
        """
        n_extracted, n_truth = similarity_matrix.shape

        # Convert to cost matrix (minimize negative similarity)
        cost_matrix = -similarity_matrix

        # Handle rectangular matrices by padding
        if n_extracted != n_truth:
            max_dim = max(n_extracted, n_truth)
            padded_cost = np.zeros((max_dim, max_dim))
            padded_cost[:n_extracted, :n_truth] = cost_matrix
            # Fill padding with high cost (low similarity)
            padded_cost[n_extracted:, :] = 1.0
            padded_cost[:, n_truth:] = 1.0
            cost_matrix = padded_cost

        # Solve assignment problem
        row_ind, col_ind = linear_sum_assignment(cost_matrix)

        # Extract valid matches above threshold
        matches = []
        matched_extracted = set()
        matched_truth = set()

        for ext_idx, truth_idx in zip(row_ind, col_ind):
            # Skip padding assignments
            if ext_idx >= n_extracted or truth_idx >= n_truth:
                continue

            similarity = similarity_matrix[ext_idx, truth_idx]
            if similarity >= self.threshold:
                matches.append((ext_idx, truth_idx, float(similarity)))
                matched_extracted.add(ext_idx)
                matched_truth.add(truth_idx)

        # Find unmatched
        unmatched_extracted = [i for i in range(n_extracted) if i not in matched_extracted]
        unmatched_truth = [i for i in range(n_truth) if i not in matched_truth]

        return matches, unmatched_extracted, unmatched_truth

    def get_similarity(self, text1: str, text2: str) -> float:
        """Get similarity score between two texts."""
        embeddings = self._model.encode([text1, text2], convert_to_numpy=True)
        embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)
        return float(np.dot(embeddings[0], embeddings[1]))
