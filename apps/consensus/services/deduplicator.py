"""
Nugget deduplication service.

Clusters semantically similar nuggets using sentence-transformer
embeddings and greedy agglomerative clustering.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class NuggetCluster:
    """A cluster of semantically similar nuggets."""
    cluster_id: int
    representative_text: str
    nugget_indices: list[int] = field(default_factory=list)
    source_names: set[str] = field(default_factory=set)

    @property
    def source_count(self) -> int:
        return len(self.source_names)


@dataclass
class DeduplicationResult:
    """Result of nugget deduplication."""
    clusters: list[NuggetCluster]
    assignments: list[int]  # cluster_id for each input nugget


class NuggetDeduplicator:
    """
    Deduplicates nuggets using semantic similarity clustering.

    Uses the same sentence-transformer model as SemanticMatcher
    for consistency, with greedy agglomerative clustering.
    """

    def __init__(self, threshold: float | None = None):
        self.threshold = threshold or getattr(
            settings, 'CONSENSUS_SIMILARITY_THRESHOLD', 0.85
        )

    def deduplicate(
        self,
        nugget_texts: list[str],
        source_names: list[str],
    ) -> DeduplicationResult:
        """
        Cluster nuggets by semantic similarity.

        Args:
            nugget_texts: List of nugget text strings.
            source_names: Parallel list — source name for each nugget.

        Returns:
            DeduplicationResult with clusters and per-nugget assignments.
        """
        if not nugget_texts:
            return DeduplicationResult(clusters=[], assignments=[])

        # Encode all nuggets
        embeddings = self._encode(nugget_texts)

        # Normalize for cosine similarity
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        embeddings_norm = embeddings / norms

        # Greedy clustering
        clusters: list[NuggetCluster] = []
        assignments = [-1] * len(nugget_texts)

        # Compute all centroid similarities at once for each new nugget
        for i in range(len(nugget_texts)):
            best_cluster_idx = -1
            best_sim = -1.0

            if clusters:
                # Compute similarity to all existing cluster centroids
                centroids = np.array([
                    self._cluster_centroid(c, embeddings_norm)
                    for c in clusters
                ])
                sims = np.dot(centroids, embeddings_norm[i])
                best_cluster_idx = int(np.argmax(sims))
                best_sim = float(sims[best_cluster_idx])

            if best_sim >= self.threshold:
                # Add to existing cluster
                cluster = clusters[best_cluster_idx]
                cluster.nugget_indices.append(i)
                cluster.source_names.add(source_names[i])
                assignments[i] = cluster.cluster_id
            else:
                # Create new cluster
                cluster_id = len(clusters)
                cluster = NuggetCluster(
                    cluster_id=cluster_id,
                    representative_text=nugget_texts[i],
                    nugget_indices=[i],
                    source_names={source_names[i]},
                )
                clusters.append(cluster)
                assignments[i] = cluster_id

        # Pick best representative for each cluster (closest to centroid)
        for cluster in clusters:
            if len(cluster.nugget_indices) > 1:
                centroid = self._cluster_centroid(cluster, embeddings_norm)
                member_embs = embeddings_norm[cluster.nugget_indices]
                sims = np.dot(member_embs, centroid)
                best_idx = cluster.nugget_indices[int(np.argmax(sims))]
                cluster.representative_text = nugget_texts[best_idx]

        return DeduplicationResult(clusters=clusters, assignments=assignments)

    def _encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts using the sentence-transformer model."""
        from apps.evaluation.services.matcher import SemanticMatcher

        model = SemanticMatcher._get_model(
            getattr(settings, 'SEMANTIC_MODEL', 'all-MiniLM-L6-v2')
        )
        return model.encode(texts, convert_to_numpy=True)

    @staticmethod
    def _cluster_centroid(
        cluster: NuggetCluster,
        embeddings_norm: np.ndarray,
    ) -> np.ndarray:
        """Compute mean centroid for a cluster."""
        member_embs = embeddings_norm[cluster.nugget_indices]
        centroid = member_embs.mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm > 0:
            centroid = centroid / norm
        return centroid
