"""
Validate the framing (political leaning) classifier against
the PoliticalBias AllSides dataset.

Runs FramingAnalyzer on each article and compares the predicted
dominant leaning to the ground truth, computing accuracy and F1.

Usage:
    python manage.py validate_framing --limit 500
    python manage.py validate_framing --limit 500 --sweep
    python manage.py validate_framing --margin 0.15 --limit 500
"""

import time

from django.core.management.base import BaseCommand
from tqdm import tqdm

from apps.analysis.services.framing import FramingAnalyzer
from apps.datasets.loaders import PoliticalBiasLoader


class Command(BaseCommand):
    help = "Validate framing classifier against PoliticalBias AllSides dataset"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of articles to evaluate",
        )
        parser.add_argument(
            "--margin",
            type=float,
            default=0.1,
            help="Margin threshold for center detection (default: 0.1)",
        )
        parser.add_argument(
            "--sweep",
            action="store_true",
            help="Sweep margin thresholds to find optimal value",
        )

    def handle(self, *args, **options):
        limit = options["limit"]

        self.stdout.write("Loading PoliticalBias AllSides dataset...")
        loader = PoliticalBiasLoader()
        articles = list(loader.load(split="train", limit=limit))
        self.stdout.write(f"Loaded {len(articles)} articles.")

        self.stdout.write("Initializing FramingAnalyzer...")
        analyzer = FramingAnalyzer()

        # Pre-compute all model predictions (expensive step, do once)
        self.stdout.write("Running model inference...")
        predictions = []
        start_time = time.time()

        for doc_data in tqdm(articles, desc="Classifying"):
            text = doc_data["primary_text"]
            gt_label = doc_data["reference_content"]["label_text"]

            result = analyzer.analyze(text)
            if result.chunks_analyzed == 0:
                continue

            predictions.append({
                'gt_label': gt_label,
                'left': result.left,
                'center': result.center,
                'right': result.right,
            })

        inference_time = time.time() - start_time
        self.stdout.write(f"Inference complete: {len(predictions)} articles in {inference_time:.1f}s")

        if options["sweep"]:
            self._run_sweep(predictions, inference_time)
        else:
            self._run_single(predictions, options["margin"], inference_time)

    def _run_sweep(self, predictions, inference_time):
        """Sweep margin thresholds to find optimal configuration."""
        margins = [0.0, 0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25, 0.30]

        self.stdout.write("\n" + "=" * 90)
        self.stdout.write("MARGIN SWEEP RESULTS")
        self.stdout.write("=" * 90)
        self.stdout.write(
            f"{'Margin':>8} {'Accuracy':>10} "
            f"{'Left R':>8} {'Center R':>10} {'Right R':>9} {'Macro F1':>10}"
        )
        self.stdout.write("-" * 90)

        best_f1 = 0.0
        best_margin = 0.0

        for margin in margins:
            metrics = self._evaluate(predictions, margin)
            if metrics is None:
                continue

            line = (
                f"{margin:>8.2f} {metrics['accuracy']:>10.4f} "
                f"{metrics['left']['recall']:>8.4f} "
                f"{metrics['center']['recall']:>10.4f} "
                f"{metrics['right']['recall']:>9.4f} "
                f"{metrics['macro_f1']:>10.4f}"
            )
            self.stdout.write(line)

            if metrics['macro_f1'] > best_f1:
                best_f1 = metrics['macro_f1']
                best_margin = margin

        self.stdout.write("-" * 90)
        self.stdout.write(f"\nBest margin: {best_margin}, macro_f1: {best_f1:.4f}")

        # Run detailed report for best margin
        self.stdout.write("\n\nDetailed results for best configuration:")
        self._run_single(predictions, best_margin, inference_time)

    def _run_single(self, predictions, margin, inference_time):
        """Run detailed validation report for a single margin value."""
        metrics = self._evaluate(predictions, margin)
        if metrics is None:
            self.stdout.write(self.style.ERROR("No articles evaluated."))
            return

        total = metrics['total']
        correct = metrics['correct']
        accuracy = metrics['accuracy']

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("FRAMING CLASSIFIER VALIDATION RESULTS")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Dataset: PoliticalBias AllSides (train split, balanced round-robin sampling)")
        self.stdout.write(f"Samples: {total}")
        self.stdout.write(f"Model:   matous-volf/political-leaning-politics")
        self.stdout.write(f"Tokenizer: launch/POLITICS")
        self.stdout.write(f"Margin threshold: {margin}")
        self.stdout.write(f"Date:    {time.strftime('%Y-%m-%d')}")
        self.stdout.write(f"\nOverall Accuracy: {accuracy:.4f} ({correct}/{total})")

        classes = ["left", "center", "right"]

        self.stdout.write(f"\n{'Class':<15} {'Precision':>10} {'Recall':>10} {'F1':>10} {'Support':>10}")
        self.stdout.write("-" * 60)

        for class_name in classes:
            m = metrics[class_name]
            self.stdout.write(
                f"{class_name:<15} {m['precision']:>10.4f} {m['recall']:>10.4f} "
                f"{m['f1']:>10.4f} {m['support']:>10}"
            )

        self.stdout.write("-" * 60)
        self.stdout.write(
            f"{'macro avg':<15} {metrics['macro_p']:>10.4f} {metrics['macro_r']:>10.4f} "
            f"{metrics['macro_f1']:>10.4f} {total:>10}"
        )

        # Confusion matrix
        cm = metrics['confusion']
        self.stdout.write(f"\nConfusion Matrix:")
        self.stdout.write(f"{'':>20} {'Pred LEFT':>12} {'Pred CENTER':>12} {'Pred RIGHT':>12}")
        for i, gt_class in enumerate(classes):
            self.stdout.write(
                f"{'Actual ' + gt_class.upper():>20} "
                f"{cm[i][0]:>12} {cm[i][1]:>12} {cm[i][2]:>12}"
            )

        # Timing
        self.stdout.write(f"\nPerformance:")
        self.stdout.write(f"  Total inference time: {inference_time:.2f}s")
        self.stdout.write(f"  Avg/article: {(inference_time / total) * 1000:.1f}ms")

        self.stdout.write("=" * 60)

    def _evaluate(self, predictions, margin):
        """Evaluate predictions with a given margin threshold. Returns metrics dict."""
        if not predictions:
            return None

        classes = ["left", "center", "right"]
        class_idx = {c: i for i, c in enumerate(classes)}

        y_true = []
        y_pred = []
        correct = 0

        for pred in predictions:
            gt_label = pred['gt_label']
            pred_label = FramingAnalyzer.classify(
                pred['left'], pred['center'], pred['right'],
                margin_threshold=margin,
            )

            y_true.append(gt_label)
            y_pred.append(pred_label)

            if pred_label == gt_label:
                correct += 1

        total = len(y_true)
        if total == 0:
            return None

        accuracy = correct / total

        # Per-class metrics
        class_metrics = {}
        macro_p = macro_r = macro_f1 = 0.0

        for class_name in classes:
            tp = sum(1 for t, p in zip(y_true, y_pred) if t == class_name and p == class_name)
            fp = sum(1 for t, p in zip(y_true, y_pred) if t != class_name and p == class_name)
            fn = sum(1 for t, p in zip(y_true, y_pred) if t == class_name and p != class_name)
            support = sum(1 for t in y_true if t == class_name)

            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

            macro_p += precision
            macro_r += recall
            macro_f1 += f1

            class_metrics[class_name] = {
                'precision': precision, 'recall': recall, 'f1': f1, 'support': support,
            }

        num_classes = len(classes)
        macro_p /= num_classes
        macro_r /= num_classes
        macro_f1 /= num_classes

        # Confusion matrix (3x3)
        cm = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        for t, p in zip(y_true, y_pred):
            cm[class_idx[t]][class_idx[p]] += 1

        return {
            'total': total,
            'correct': correct,
            'accuracy': accuracy,
            'macro_p': macro_p,
            'macro_r': macro_r,
            'macro_f1': macro_f1,
            'confusion': cm,
            **class_metrics,
        }
