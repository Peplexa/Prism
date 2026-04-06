"""
Scoring for nugget-based evaluation.

Supports both traditional F1 scoring and AutoNuggetizer-style recall metrics.

Based on: "The Great Nugget Recall: Automating Fact Extraction and RAG
Evaluation with Large Language Models" (Pradeep et al., 2025)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .auto_assigner import AutoAssignResult

from .matcher import MatchingResult


@dataclass
class ScoreResult:
    """Aggregated scoring results."""

    precision: float
    recall: float
    f1_score: float
    true_positives: int
    false_positives: int
    false_negatives: int
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1_score": self.f1_score,
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "details": self.details,
        }


@dataclass
class AutoNuggetScoreResult:
    """
    Scoring results following the AutoNuggetizer methodology.

    The paper focuses on nugget recall rather than F1, with metrics:
    - A_strict: Recall over ALL nuggets (strict matching)
    - V_strict: Recall over VITAL nuggets only (strict matching)
    - Support/Partial/NotSupport counts
    """

    # Strict recall (only full support counts)
    recall_strict: float

    # Lenient recall (partial support = 0.5)
    recall_lenient: float

    # Raw counts
    support_count: int
    partial_support_count: int
    not_support_count: int
    total_nuggets: int

    # Optional: vital nugget metrics (if importance labels available)
    vital_recall_strict: float | None = None
    vital_support_count: int | None = None
    vital_total: int | None = None

    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "recall_strict": self.recall_strict,
            "recall_lenient": self.recall_lenient,
            "support_count": self.support_count,
            "partial_support_count": self.partial_support_count,
            "not_support_count": self.not_support_count,
            "total_nuggets": self.total_nuggets,
            "details": self.details,
        }
        if self.vital_recall_strict is not None:
            result["vital_recall_strict"] = self.vital_recall_strict
            result["vital_support_count"] = self.vital_support_count
            result["vital_total"] = self.vital_total
        return result


class F1Calculator:
    """
    Calculate F1 score for omission detection.

    Terminology:
    - True Positive: Ground truth fact correctly identified in extracted nuggets
    - False Positive: Extracted nugget not matching any ground truth (hallucination)
    - False Negative: Ground truth fact not found (OMISSION - this is what we care about)

    Precision = TP / (TP + FP) - How many extracted nuggets are real facts
    Recall = TP / (TP + FN) - How many real facts were extracted (1 - omission rate)
    F1 = 2 * P * R / (P + R)
    """

    def calculate(self, matching_result: MatchingResult) -> ScoreResult:
        """
        Calculate precision, recall, and F1 from matching result.

        Args:
            matching_result: Result from SemanticMatcher.match()

        Returns:
            ScoreResult with all metrics
        """
        tp = len(matching_result.matches)
        fp = len(matching_result.unmatched_extracted)  # Hallucinations
        fn = len(matching_result.unmatched_truth)  # Omissions

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        # Calculate additional metrics
        total_truth = tp + fn
        total_extracted = tp + fp
        omission_rate = fn / total_truth if total_truth > 0 else 0.0
        hallucination_rate = fp / total_extracted if total_extracted > 0 else 0.0

        # Average similarity of matches
        avg_similarity = 0.0
        if matching_result.matches:
            avg_similarity = sum(m[2] for m in matching_result.matches) / len(
                matching_result.matches
            )

        return ScoreResult(
            precision=precision,
            recall=recall,
            f1_score=f1,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            details={
                "omission_rate": omission_rate,
                "hallucination_rate": hallucination_rate,
                "average_similarity": avg_similarity,
                "total_ground_truth": total_truth,
                "total_extracted": total_extracted,
            },
        )

    def calculate_from_counts(
        self,
        true_positives: int,
        false_positives: int,
        false_negatives: int,
    ) -> ScoreResult:
        """Calculate scores directly from counts."""
        tp, fp, fn = true_positives, false_positives, false_negatives

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        return ScoreResult(
            precision=precision,
            recall=recall,
            f1_score=f1,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
        )

    def aggregate(self, results: list[ScoreResult]) -> ScoreResult:
        """
        Aggregate multiple ScoreResults into a single result.

        Uses micro-averaging (sum all TP/FP/FN then calculate).
        """
        if not results:
            return ScoreResult(
                precision=0.0,
                recall=0.0,
                f1_score=0.0,
                true_positives=0,
                false_positives=0,
                false_negatives=0,
            )

        total_tp = sum(r.true_positives for r in results)
        total_fp = sum(r.false_positives for r in results)
        total_fn = sum(r.false_negatives for r in results)

        result = self.calculate_from_counts(total_tp, total_fp, total_fn)

        # Add aggregation details
        result.details["num_documents"] = len(results)
        result.details["per_document_f1_mean"] = sum(r.f1_score for r in results) / len(results)
        result.details["per_document_f1_std"] = (
            sum((r.f1_score - result.details["per_document_f1_mean"]) ** 2 for r in results)
            / len(results)
        ) ** 0.5

        return result


class AutoNuggetScorer:
    """
    Calculate scores following the AutoNuggetizer methodology.

    This focuses on nugget RECALL rather than F1, measuring how many
    ground truth facts are captured by the system's output.

    From the paper:
    - A_strict: Strict recall over all nuggets (only full support counts)
    - V_strict: Strict recall over vital nuggets only
    """

    def calculate(self, auto_result: AutoAssignResult) -> AutoNuggetScoreResult:
        """
        Calculate AutoNuggetizer-style scores from assignment result.

        Args:
            auto_result: Result from AutoAssigner.assign()

        Returns:
            AutoNuggetScoreResult with recall metrics
        """
        from .auto_assigner import AssignmentLabel

        total = len(auto_result.assignments)
        if total == 0:
            return AutoNuggetScoreResult(
                recall_strict=0.0,
                recall_lenient=0.0,
                support_count=0,
                partial_support_count=0,
                not_support_count=0,
                total_nuggets=0,
            )

        support = auto_result.support_count
        partial = auto_result.partial_support_count
        not_support = auto_result.not_support_count

        # Strict recall: only full support counts
        recall_strict = support / total

        # Lenient recall: partial support counts as 0.5
        recall_lenient = (support + 0.5 * partial) / total

        return AutoNuggetScoreResult(
            recall_strict=recall_strict,
            recall_lenient=recall_lenient,
            support_count=support,
            partial_support_count=partial,
            not_support_count=not_support,
            total_nuggets=total,
        )

    def aggregate(self, results: list[AutoNuggetScoreResult]) -> AutoNuggetScoreResult:
        """
        Aggregate multiple AutoNuggetScoreResults.

        Uses micro-averaging (sum all counts then calculate).
        """
        if not results:
            return AutoNuggetScoreResult(
                recall_strict=0.0,
                recall_lenient=0.0,
                support_count=0,
                partial_support_count=0,
                not_support_count=0,
                total_nuggets=0,
            )

        total_support = sum(r.support_count for r in results)
        total_partial = sum(r.partial_support_count for r in results)
        total_not_support = sum(r.not_support_count for r in results)
        total_nuggets = sum(r.total_nuggets for r in results)

        if total_nuggets == 0:
            recall_strict = 0.0
            recall_lenient = 0.0
        else:
            recall_strict = total_support / total_nuggets
            recall_lenient = (total_support + 0.5 * total_partial) / total_nuggets

        result = AutoNuggetScoreResult(
            recall_strict=recall_strict,
            recall_lenient=recall_lenient,
            support_count=total_support,
            partial_support_count=total_partial,
            not_support_count=total_not_support,
            total_nuggets=total_nuggets,
        )

        # Add aggregation details
        result.details["num_documents"] = len(results)
        result.details["per_document_recall_strict_mean"] = (
            sum(r.recall_strict for r in results) / len(results)
        )
        result.details["per_document_recall_lenient_mean"] = (
            sum(r.recall_lenient for r in results) / len(results)
        )

        return result
