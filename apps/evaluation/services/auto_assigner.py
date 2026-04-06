"""
LLM-based nugget assignment following the AutoNuggetizer methodology.

Based on: "The Great Nugget Recall: Automating Fact Extraction and RAG
Evaluation with Large Language Models" (Pradeep et al., 2025)

This module implements AutoAssign - using an LLM to determine whether
each ground truth fact is supported, partially supported, or not supported
by the extracted nuggets.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from apps.extraction.services.llm_client import BaseLLMClient, get_llm_client

logger = logging.getLogger(__name__)


class AssignmentLabel(Enum):
    """Labels for nugget assignment."""
    SUPPORT = "support"
    PARTIAL_SUPPORT = "partial_support"
    NOT_SUPPORT = "not_support"


@dataclass
class NuggetAssignment:
    """Assignment result for a single ground truth fact."""
    fact_index: int
    fact_text: str
    label: AssignmentLabel
    confidence: float = 1.0


@dataclass
class AutoAssignResult:
    """Result of LLM-based nugget assignment for a document."""
    assignments: list[NuggetAssignment]

    @property
    def support_count(self) -> int:
        return sum(1 for a in self.assignments if a.label == AssignmentLabel.SUPPORT)

    @property
    def partial_support_count(self) -> int:
        return sum(1 for a in self.assignments if a.label == AssignmentLabel.PARTIAL_SUPPORT)

    @property
    def not_support_count(self) -> int:
        return sum(1 for a in self.assignments if a.label == AssignmentLabel.NOT_SUPPORT)

    def get_recall_strict(self) -> float:
        """Calculate recall with strict matching (only full support counts)."""
        total = len(self.assignments)
        if total == 0:
            return 0.0
        return self.support_count / total

    def get_recall_lenient(self) -> float:
        """Calculate recall with lenient matching (partial support = 0.5)."""
        total = len(self.assignments)
        if total == 0:
            return 0.0
        score = self.support_count + 0.5 * self.partial_support_count
        return score / total


# System prompt following the AutoNuggetizer paper (Figure 3)
AUTO_ASSIGN_SYSTEM_PROMPT = """You are NuggetAssignerLLM, an intelligent assistant that labels atomic nuggets based on whether they are captured by a given passage.

Your task is to determine if each fact/nugget from a ground truth list is present (fully, partially, or not at all) in the system-generated answer.

Be precise and consistent in your assessments."""

# User prompt template following the AutoNuggetizer paper (Figure 3)
AUTO_ASSIGN_USER_TEMPLATE = """Based on the query context and the system answer, label each of the {num_nuggets} ground truth facts using the following criteria:

- "support": The fact is FULLY captured in the answer (all key information present)
- "partial_support": The fact is PARTIALLY captured in the answer (some key information present but incomplete)
- "not_support": The fact is NOT captured at all in the answer

Context: {context}

System Answer:
{answer}

Ground Truth Facts to Evaluate:
{nugget_list}

Return ONLY a JSON array of labels in the same order as the input facts.
Example: ["support", "not_support", "partial_support", ...]

Labels:"""


class AutoAssigner:
    """
    LLM-based nugget assignment following the AutoNuggetizer methodology.

    Instead of using semantic similarity to match extracted nuggets to ground truth,
    this class uses an LLM to directly assess whether each ground truth fact is
    supported by the system's extracted nuggets.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient | None = None,
        backend: str | None = None,
        batch_size: int = 10,
    ):
        """
        Initialize the AutoAssigner.

        Args:
            llm_client: LLM client instance (creates new one if None)
            backend: LLM backend to use ('ollama', 'deepseek')
            batch_size: Number of nuggets to evaluate per LLM call (paper uses 10)
        """
        self.llm_client = llm_client or get_llm_client(backend)
        self.batch_size = batch_size

    def assign(
        self,
        extracted_nuggets: list[str],
        ground_truth_facts: list[str],
        context: str = "",
    ) -> AutoAssignResult:
        """
        Assign ground truth facts to extracted nuggets using LLM.

        This inverts the typical matching direction: instead of finding which
        ground truth each extracted nugget matches, we assess which ground truth
        facts are covered by the full set of extracted nuggets.

        Args:
            extracted_nuggets: List of nuggets extracted by the system
            ground_truth_facts: List of ground truth facts to evaluate
            context: Optional context (e.g., original query or document title)

        Returns:
            AutoAssignResult with assignment labels for each ground truth fact
        """
        if not ground_truth_facts:
            return AutoAssignResult(assignments=[])

        # Combine extracted nuggets into a single "answer" for evaluation
        if extracted_nuggets:
            answer = "\n".join(f"- {nugget}" for nugget in extracted_nuggets)
        else:
            answer = "(No facts were extracted)"

        # Process in batches
        all_assignments = []

        for batch_start in range(0, len(ground_truth_facts), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(ground_truth_facts))
            batch_facts = ground_truth_facts[batch_start:batch_end]

            batch_assignments = self._assign_batch(
                answer=answer,
                facts=batch_facts,
                fact_start_index=batch_start,
                context=context,
            )
            all_assignments.extend(batch_assignments)

        return AutoAssignResult(assignments=all_assignments)

    def _assign_batch(
        self,
        answer: str,
        facts: list[str],
        fact_start_index: int,
        context: str,
    ) -> list[NuggetAssignment]:
        """Assign a batch of facts using a single LLM call."""

        # Format the nugget list
        nugget_list = "\n".join(
            f"[{i+1}] {fact}" for i, fact in enumerate(facts)
        )

        # Build the prompt
        user_prompt = AUTO_ASSIGN_USER_TEMPLATE.format(
            num_nuggets=len(facts),
            context=context or "(General fact extraction)",
            answer=answer,
            nugget_list=nugget_list,
        )

        # Call the LLM
        try:
            response = self.llm_client.generate(
                prompt=user_prompt,
                system=AUTO_ASSIGN_SYSTEM_PROMPT,
                temperature=0.0,  # Deterministic for evaluation
            )

            labels = self._parse_labels(response, len(facts))

        except Exception as e:
            logger.error(f"LLM assignment failed: {e}")
            # Default to not_support on error
            labels = [AssignmentLabel.NOT_SUPPORT] * len(facts)

        # Build assignment objects
        assignments = []
        for i, (fact, label) in enumerate(zip(facts, labels)):
            assignments.append(NuggetAssignment(
                fact_index=fact_start_index + i,
                fact_text=fact,
                label=label,
            ))

        return assignments

    def _parse_labels(self, response: str, expected_count: int) -> list[AssignmentLabel]:
        """Parse LLM response into assignment labels."""

        # Try to extract JSON array from response
        # Handle various response formats the LLM might produce

        # Clean up response - remove thinking tags if present (DeepSeek R1)
        response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
        response = response.strip()

        # Try direct JSON parse
        try:
            labels_raw = json.loads(response)
            if isinstance(labels_raw, list):
                return self._convert_labels(labels_raw, expected_count)
        except json.JSONDecodeError:
            pass

        # Try to find JSON array in response
        json_match = re.search(r'\[.*?\]', response, re.DOTALL)
        if json_match:
            try:
                labels_raw = json.loads(json_match.group())
                if isinstance(labels_raw, list):
                    return self._convert_labels(labels_raw, expected_count)
            except json.JSONDecodeError:
                pass

        # Try line-by-line parsing
        lines = response.strip().split('\n')
        labels = []
        for line in lines:
            line_lower = line.lower().strip()
            if 'partial' in line_lower:
                labels.append(AssignmentLabel.PARTIAL_SUPPORT)
            elif 'support' in line_lower and 'not' not in line_lower:
                labels.append(AssignmentLabel.SUPPORT)
            elif 'not' in line_lower or 'no' in line_lower:
                labels.append(AssignmentLabel.NOT_SUPPORT)

        if len(labels) >= expected_count:
            return labels[:expected_count]

        # Fallback: pad with not_support
        logger.warning(
            f"Could not parse {expected_count} labels from response, "
            f"got {len(labels)}. Response: {response[:200]}..."
        )
        while len(labels) < expected_count:
            labels.append(AssignmentLabel.NOT_SUPPORT)

        return labels

    def _convert_labels(
        self,
        raw_labels: list[Any],
        expected_count: int
    ) -> list[AssignmentLabel]:
        """Convert raw string labels to AssignmentLabel enum."""
        labels = []

        for label in raw_labels:
            label_str = str(label).lower().strip()

            if label_str in ('support', 'supported', 'yes', 'full', 'full_support'):
                labels.append(AssignmentLabel.SUPPORT)
            elif label_str in ('partial_support', 'partial', 'partially', 'partially_supported'):
                labels.append(AssignmentLabel.PARTIAL_SUPPORT)
            else:
                labels.append(AssignmentLabel.NOT_SUPPORT)

        # Pad or truncate to expected count
        while len(labels) < expected_count:
            labels.append(AssignmentLabel.NOT_SUPPORT)

        return labels[:expected_count]


def convert_to_matching_result(
    auto_result: AutoAssignResult,
    extracted_nuggets: list[str],
    ground_truth_facts: list[str],
    include_partial_as_match: bool = False,
) -> "MatchingResult":
    """
    Convert AutoAssignResult to the legacy MatchingResult format for compatibility.

    This allows the AutoAssigner to be used with existing scoring code.

    Args:
        auto_result: Result from AutoAssigner
        extracted_nuggets: Original extracted nuggets list
        ground_truth_facts: Original ground truth facts list
        include_partial_as_match: If True, partial_support counts as a match

    Returns:
        MatchingResult compatible with F1Calculator
    """
    from .matcher import MatchingResult

    matches = []
    unmatched_truth = []

    for assignment in auto_result.assignments:
        is_match = (
            assignment.label == AssignmentLabel.SUPPORT or
            (include_partial_as_match and assignment.label == AssignmentLabel.PARTIAL_SUPPORT)
        )

        if is_match:
            # For matches, we assign to a "virtual" extracted nugget
            # The similarity score reflects the assignment quality
            similarity = 1.0 if assignment.label == AssignmentLabel.SUPPORT else 0.5
            matches.append((0, assignment.fact_index, similarity))
        else:
            unmatched_truth.append(assignment.fact_index)

    # All extracted nuggets that didn't contribute to matches
    # In the AutoNuggetizer approach, we focus on recall of ground truth
    # so we don't penalize "extra" extracted nuggets as heavily
    unmatched_extracted = []

    return MatchingResult(
        matches=matches,
        unmatched_extracted=unmatched_extracted,
        unmatched_truth=unmatched_truth,
    )
