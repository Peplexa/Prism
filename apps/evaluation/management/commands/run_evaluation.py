"""
Management command to evaluate extracted nuggets against ground truth.

Supports both traditional semantic matching and AutoNuggetizer-style
LLM-based nugget assignment.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone
from tqdm import tqdm

from apps.datasets.models import Document, GroundTruthFact
from apps.evaluation.models import EvaluationRun, MatchResult, ScoreReport
from apps.evaluation.services import (
    F1Calculator,
    SemanticMatcher,
    AutoAssigner,
    AutoNuggetScorer,
    AssignmentLabel,
)
from apps.extraction.models import ExtractedNugget, ExtractionRun


class Command(BaseCommand):
    help = "Evaluate extracted nuggets against ground truth"

    def add_arguments(self, parser):
        parser.add_argument(
            "--extraction-run",
            required=True,
            type=int,
            help="ExtractionRun ID to evaluate",
        )
        parser.add_argument(
            "--threshold",
            type=float,
            default=0.8,
            help="Similarity threshold for semantic matching (default: 0.8)",
        )
        parser.add_argument(
            "--matcher",
            default="llm",
            choices=["semantic", "llm"],
            help="Matcher type: 'semantic' (similarity) or 'llm' (AutoNuggetizer)",
        )
        parser.add_argument(
            "--include-partial",
            action="store_true",
            help="Count partial_support as matches in scoring (LLM matcher only)",
        )
        parser.add_argument(
            "--backend",
            default=None,
            choices=["ollama", "deepseek"],
            help="LLM backend for evaluation: 'ollama' (local) or 'deepseek' (cloud)",
        )
        parser.add_argument(
            "--filter-to-summary",
            action="store_true",
            help="Filter ground truth to only include players mentioned in summary (Rotowire only)",
        )
        parser.add_argument(
            "--filter-strict",
            action="store_true",
            help="Strict filtering: only include facts whose values appear in summary text (Rotowire only)",
        )

    def handle(self, *args, **options):
        extraction_run_id = options["extraction_run"]
        threshold = options["threshold"]
        matcher_type = options["matcher"]
        include_partial = options["include_partial"]
        backend = options["backend"]
        filter_to_summary = options["filter_to_summary"]
        filter_strict = options["filter_strict"]

        # Get extraction run
        try:
            extraction_run = ExtractionRun.objects.get(pk=extraction_run_id)
        except ExtractionRun.DoesNotExist:
            self.stderr.write(
                self.style.ERROR(f"ExtractionRun {extraction_run_id} not found")
            )
            return

        self.stdout.write(f"Evaluating extraction run: {extraction_run.name}")
        self.stdout.write(f"Matcher: {matcher_type}")
        if filter_strict:
            self.stdout.write(self.style.SUCCESS("Strict filtering: only facts with values stated in text"))
        elif filter_to_summary:
            self.stdout.write(self.style.SUCCESS("Filtering ground truth to summary-mentioned players"))

        # Create evaluation run
        matcher_config = {"threshold": threshold}
        if matcher_type == "llm":
            matcher_config["include_partial"] = include_partial
        if filter_to_summary:
            matcher_config["filter_to_summary"] = True
        if filter_strict:
            matcher_config["filter_strict"] = True

        evaluation_run = EvaluationRun.objects.create(
            extraction_run=extraction_run,
            matcher_type=matcher_type,
            matcher_config=matcher_config,
            status="running",
            started_at=timezone.now(),
        )

        # Get all documents that have extracted nuggets
        doc_ids = ExtractedNugget.objects.filter(
            extraction_run=extraction_run
        ).values_list("document_id", flat=True).distinct()

        documents = Document.objects.filter(pk__in=doc_ids)
        total_docs = documents.count()

        if total_docs == 0:
            self.stderr.write(
                self.style.ERROR("No documents with extracted nuggets found")
            )
            evaluation_run.status = "failed"
            evaluation_run.error_message = "No documents found"
            evaluation_run.save()
            return

        self.stdout.write(f"Evaluating {total_docs} documents...")

        if matcher_type == "llm":
            self._evaluate_with_llm(
                evaluation_run, extraction_run, documents, include_partial, backend, filter_to_summary, filter_strict
            )
        else:
            self._evaluate_with_semantic(
                evaluation_run, extraction_run, documents, threshold, filter_to_summary, filter_strict
            )

    def _evaluate_with_llm(
        self,
        evaluation_run: EvaluationRun,
        extraction_run: ExtractionRun,
        documents,
        include_partial: bool,
        backend: str | None = None,
        filter_to_summary: bool = False,
        filter_strict: bool = False,
    ):
        """Evaluate using LLM-based AutoAssigner (AutoNuggetizer approach)."""
        assigner = AutoAssigner(backend=backend)
        scorer = AutoNuggetScorer()
        document_scores = []

        for doc in tqdm(documents, desc="Evaluating"):
            # Get extracted nuggets for this document
            extracted = list(
                ExtractedNugget.objects.filter(
                    extraction_run=extraction_run,
                    document=doc,
                ).values_list("pk", "nugget_text")
            )

            # Get ground truth facts (optionally filtered)
            if filter_strict and doc.source.name == "rotowire":
                ground_truth = self._get_strict_filtered_ground_truth(doc)
            elif filter_to_summary and doc.source.name == "rotowire":
                ground_truth = self._get_filtered_ground_truth(doc)
            else:
                ground_truth = list(
                    GroundTruthFact.objects.filter(document=doc).values_list(
                        "pk", "fact_text"
                    )
                )

            if not ground_truth:
                continue

            # Extract texts
            extracted_ids, extracted_texts = (
                zip(*extracted) if extracted else ([], [])
            )
            truth_ids, truth_texts = zip(*ground_truth)

            # Run LLM assignment
            result = assigner.assign(
                extracted_nuggets=list(extracted_texts),
                ground_truth_facts=list(truth_texts),
                context=doc.title or f"Document {doc.external_id}",
            )

            # Store match results
            for assignment in result.assignments:
                match_type = assignment.label.value  # support/partial_support/not_support

                MatchResult.objects.create(
                    evaluation_run=evaluation_run,
                    document=doc,
                    extracted_nugget=None,  # LLM assigns to ground truth, not individual nuggets
                    ground_truth_fact_id=truth_ids[assignment.fact_index],
                    similarity_score=1.0 if assignment.label == AssignmentLabel.SUPPORT else (
                        0.5 if assignment.label == AssignmentLabel.PARTIAL_SUPPORT else 0.0
                    ),
                    match_type=match_type,
                )

            # Calculate document-level score
            doc_score = scorer.calculate(result)
            document_scores.append(doc_score)

        # Calculate aggregate scores
        aggregate_score = scorer.aggregate(document_scores)

        # Convert to ScoreReport format
        # For compatibility, map to precision/recall/F1
        # In AutoNuggetizer, we focus on recall (nugget coverage)
        tp = aggregate_score.support_count
        if include_partial:
            tp += aggregate_score.partial_support_count
        fp = 0  # AutoNuggetizer doesn't penalize extra extracted nuggets
        fn = aggregate_score.not_support_count
        if not include_partial:
            fn += aggregate_score.partial_support_count

        precision = 1.0  # Not measuring precision in AutoNuggetizer
        recall = aggregate_score.recall_strict if not include_partial else aggregate_score.recall_lenient
        f1 = recall  # F1 = recall when precision = 1

        ScoreReport.objects.create(
            evaluation_run=evaluation_run,
            precision=precision,
            recall=recall,
            f1_score=f1,
            true_positives=tp,
            false_positives=fp,
            false_negatives=fn,
            detailed_metrics={
                "recall_strict": aggregate_score.recall_strict,
                "recall_lenient": aggregate_score.recall_lenient,
                "support_count": aggregate_score.support_count,
                "partial_support_count": aggregate_score.partial_support_count,
                "not_support_count": aggregate_score.not_support_count,
                "total_nuggets": aggregate_score.total_nuggets,
                **aggregate_score.details,
            },
        )

        # Finalize evaluation run
        evaluation_run.status = "completed"
        evaluation_run.completed_at = timezone.now()
        evaluation_run.save()

        # Print results
        self._print_llm_results(aggregate_score, len(document_scores), include_partial, evaluation_run)

    def _print_llm_results(self, score, num_docs, include_partial, evaluation_run):
        """Print AutoNuggetizer-style results."""
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS("AUTONUGGETIZER EVALUATION RESULTS"))
        self.stdout.write("=" * 50)
        self.stdout.write(f"Documents evaluated: {num_docs}")
        self.stdout.write(f"Total ground truth facts: {score.total_nuggets}")
        self.stdout.write("-" * 50)
        self.stdout.write(self.style.SUCCESS(f"Recall (Strict):  {score.recall_strict:.4f}"))
        self.stdout.write(f"Recall (Lenient): {score.recall_lenient:.4f}")
        self.stdout.write("-" * 50)
        self.stdout.write(f"Full Support:     {score.support_count}")
        self.stdout.write(f"Partial Support:  {score.partial_support_count}")
        self.stdout.write(f"Not Supported:    {score.not_support_count}")
        self.stdout.write("-" * 50)

        target_recall = 0.85
        effective_recall = score.recall_lenient if include_partial else score.recall_strict

        if effective_recall >= target_recall:
            self.stdout.write(
                self.style.SUCCESS(f"\nTarget Recall >= {target_recall} ACHIEVED!")
            )
        else:
            gap = target_recall - effective_recall
            self.stdout.write(
                self.style.WARNING(f"\nRecall gap to target: {gap:.4f}")
            )

        self.stdout.write(f"\nEvaluation Run ID: {evaluation_run.pk}")

    def _evaluate_with_semantic(
        self,
        evaluation_run: EvaluationRun,
        extraction_run: ExtractionRun,
        documents,
        threshold: float,
        filter_to_summary: bool = False,
        filter_strict: bool = False,
    ):
        """Evaluate using traditional semantic similarity matching."""
        matcher = SemanticMatcher(threshold=threshold)
        calculator = F1Calculator()
        document_scores = []

        for doc in tqdm(documents, desc="Evaluating"):
            # Get extracted nuggets for this document
            extracted = list(
                ExtractedNugget.objects.filter(
                    extraction_run=extraction_run,
                    document=doc,
                ).values_list("pk", "nugget_text")
            )

            # Get ground truth facts (optionally filtered)
            if filter_strict and doc.source.name == "rotowire":
                ground_truth = self._get_strict_filtered_ground_truth(doc)
            elif filter_to_summary and doc.source.name == "rotowire":
                ground_truth = self._get_filtered_ground_truth(doc)
            else:
                ground_truth = list(
                    GroundTruthFact.objects.filter(document=doc).values_list(
                        "pk", "fact_text"
                    )
                )

            if not ground_truth:
                continue

            # Extract texts
            extracted_ids, extracted_texts = (
                zip(*extracted) if extracted else ([], [])
            )
            truth_ids, truth_texts = zip(*ground_truth)

            # Match
            result = matcher.match(list(extracted_texts), list(truth_texts))

            # Store match results
            # True positives
            for ext_idx, truth_idx, similarity in result.matches:
                MatchResult.objects.create(
                    evaluation_run=evaluation_run,
                    document=doc,
                    extracted_nugget_id=extracted_ids[ext_idx],
                    ground_truth_fact_id=truth_ids[truth_idx],
                    similarity_score=similarity,
                    match_type="true_positive",
                )

            # False positives (hallucinations)
            for ext_idx in result.unmatched_extracted:
                MatchResult.objects.create(
                    evaluation_run=evaluation_run,
                    document=doc,
                    extracted_nugget_id=extracted_ids[ext_idx],
                    ground_truth_fact=None,
                    similarity_score=None,
                    match_type="false_positive",
                )

            # False negatives (omissions)
            for truth_idx in result.unmatched_truth:
                MatchResult.objects.create(
                    evaluation_run=evaluation_run,
                    document=doc,
                    extracted_nugget=None,
                    ground_truth_fact_id=truth_ids[truth_idx],
                    similarity_score=None,
                    match_type="false_negative",
                )

            # Calculate document-level score
            doc_score = calculator.calculate(result)
            document_scores.append(doc_score)

        # Calculate aggregate scores
        aggregate_score = calculator.aggregate(document_scores)

        # Create score report
        ScoreReport.objects.create(
            evaluation_run=evaluation_run,
            precision=aggregate_score.precision,
            recall=aggregate_score.recall,
            f1_score=aggregate_score.f1_score,
            true_positives=aggregate_score.true_positives,
            false_positives=aggregate_score.false_positives,
            false_negatives=aggregate_score.false_negatives,
            detailed_metrics=aggregate_score.details,
        )

        # Finalize evaluation run
        evaluation_run.status = "completed"
        evaluation_run.completed_at = timezone.now()
        evaluation_run.save()

        # Print results
        self._print_semantic_results(aggregate_score, threshold, evaluation_run)

    def _print_semantic_results(self, score, threshold, evaluation_run):
        """Print traditional F1 results."""
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS("EVALUATION RESULTS"))
        self.stdout.write("=" * 50)
        self.stdout.write(f"Threshold: {threshold}")
        self.stdout.write(f"Documents evaluated: {score.details.get('num_documents', 'N/A')}")
        self.stdout.write("-" * 50)
        self.stdout.write(f"Precision: {score.precision:.4f}")
        self.stdout.write(f"Recall:    {score.recall:.4f}")
        self.stdout.write(
            self.style.SUCCESS(f"F1 Score:  {score.f1_score:.4f}")
        )
        self.stdout.write("-" * 50)
        self.stdout.write(f"True Positives:  {score.true_positives}")
        self.stdout.write(f"False Positives: {score.false_positives} (hallucinations)")
        self.stdout.write(f"False Negatives: {score.false_negatives} (omissions)")
        self.stdout.write("-" * 50)

        omission_rate = score.details.get("omission_rate", 0)
        self.stdout.write(f"Omission Rate: {omission_rate:.2%}")

        if score.f1_score >= 0.85:
            self.stdout.write(
                self.style.SUCCESS("\nTarget F1 >= 0.85 ACHIEVED!")
            )
        else:
            gap = 0.85 - score.f1_score
            self.stdout.write(
                self.style.WARNING(f"\nF1 gap to target: {gap:.4f}")
            )

        self.stdout.write(f"\nEvaluation Run ID: {evaluation_run.pk}")

    def _get_filtered_ground_truth(self, doc: Document) -> list[tuple[int, str]]:
        """
        Get ground truth facts filtered to players mentioned in the summary.

        Args:
            doc: Document with Rotowire data

        Returns:
            List of (pk, fact_text) tuples for filtered facts
        """
        from apps.datasets.loaders import RotowireLoader

        loader = RotowireLoader()

        # Get all ground truth facts for this document
        all_facts = list(GroundTruthFact.objects.filter(document=doc))

        # Convert to dict format for filtering
        fact_dicts = [
            {
                "pk": f.pk,
                "fact_text": f.fact_text,
                "fact_type": f.fact_type,
                "metadata": f.metadata,
            }
            for f in all_facts
        ]

        # Filter to mentioned players
        box_score = doc.reference_content.get("box_score", {})
        filtered = loader.filter_ground_truth_to_summary(
            fact_dicts,
            doc.primary_text,
            box_score,
        )

        # Return as (pk, fact_text) tuples
        return [(f["pk"], f["fact_text"]) for f in filtered]

    def _get_strict_filtered_ground_truth(self, doc: Document) -> list[tuple[int, str]]:
        """
        Get ground truth facts filtered strictly to facts whose values appear in text.

        This is stricter than _get_filtered_ground_truth - it requires the stat
        value to actually appear in the summary, not just the player name.

        Args:
            doc: Document with Rotowire data

        Returns:
            List of (pk, fact_text) tuples for filtered facts
        """
        from apps.datasets.loaders import RotowireLoader

        loader = RotowireLoader()

        # Get all ground truth facts for this document
        all_facts = list(GroundTruthFact.objects.filter(document=doc))

        # Convert to dict format for filtering
        fact_dicts = [
            {
                "pk": f.pk,
                "fact_text": f.fact_text,
                "fact_type": f.fact_type,
                "metadata": f.metadata,
            }
            for f in all_facts
        ]

        # Use strict filtering
        box_score = doc.reference_content.get("box_score", {})
        filtered = loader.filter_ground_truth_to_stated_facts(
            fact_dicts,
            doc.primary_text,
            box_score,
        )

        # Return as (pk, fact_text) tuples
        return [(f["pk"], f["fact_text"]) for f in filtered]
