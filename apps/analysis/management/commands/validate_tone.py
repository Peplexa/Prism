"""
Validate the tone (subjectivity) classifier against the SUBJ dataset.

Runs ToneAnalyzer on each SUBJ sentence and compares the predicted label
to the ground truth, computing accuracy, precision, recall, and F1.

Usage:
    python manage.py validate_tone --limit 500
    python manage.py validate_tone --split test --limit 2000
    python manage.py validate_tone --split test --limit 500 --sweep
    python manage.py validate_tone --threshold 0.8 --limit 500
"""

import time

from django.core.management.base import BaseCommand
from tqdm import tqdm

from apps.analysis.services.tone import ToneAnalyzer
from apps.datasets.loaders import SUBJLoader


class Command(BaseCommand):
    help = "Validate tone classifier against SUBJ dataset"

    def add_arguments(self, parser):
        parser.add_argument(
            "--split",
            default="test",
            choices=["train", "test"],
            help="Data split to evaluate on (default: test)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of sentences to evaluate",
        )
        parser.add_argument(
            "--threshold",
            type=float,
            default=0.75,
            help="Confidence threshold for subjective classification (default: 0.75)",
        )
        parser.add_argument(
            "--min-words",
            type=int,
            default=5,
            help="Minimum words per sentence (default: 5)",
        )
        parser.add_argument(
            "--sweep",
            action="store_true",
            help="Sweep thresholds to find optimal value",
        )

    def handle(self, *args, **options):
        split = options["split"]
        limit = options["limit"]

        self.stdout.write(f"Loading SUBJ {split} split...")
        loader = SUBJLoader()
        sentences = list(loader.load(split=split, limit=limit))
        self.stdout.write(f"Loaded {len(sentences)} sentences.")

        if options["sweep"]:
            self._run_sweep(sentences, options)
        else:
            self._run_single(
                sentences,
                threshold=options["threshold"],
                min_words=options["min_words"],
            )

    def _run_sweep(self, sentences, options):
        """Sweep thresholds and min_words to find optimal configuration."""
        thresholds = [0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]
        min_words_options = [5, 8]

        self.stdout.write("\nInitializing ToneAnalyzer (model loads once)...")
        # Warm up the model with a dummy run
        ToneAnalyzer(confidence_threshold=0.5, min_words=5)

        best_f1 = 0.0
        best_config = {}

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write("THRESHOLD SWEEP RESULTS")
        self.stdout.write("=" * 80)
        self.stdout.write(
            f"{'Threshold':>10} {'MinWords':>10} {'Accuracy':>10} "
            f"{'OBJ Recall':>12} {'SUBJ Recall':>12} {'Macro F1':>10}"
        )
        self.stdout.write("-" * 80)

        for min_words in min_words_options:
            for threshold in thresholds:
                metrics = self._evaluate(sentences, threshold, min_words, show_progress=False)
                if metrics is None:
                    continue

                line = (
                    f"{threshold:>10.2f} {min_words:>10} {metrics['accuracy']:>10.4f} "
                    f"{metrics['obj_recall']:>12.4f} {metrics['subj_recall']:>12.4f} "
                    f"{metrics['macro_f1']:>10.4f}"
                )
                self.stdout.write(line)

                if metrics['macro_f1'] > best_f1:
                    best_f1 = metrics['macro_f1']
                    best_config = {
                        'threshold': threshold,
                        'min_words': min_words,
                        'metrics': metrics,
                    }

        self.stdout.write("-" * 80)
        self.stdout.write(
            f"\nBest config: threshold={best_config['threshold']}, "
            f"min_words={best_config['min_words']}, "
            f"macro_f1={best_config['metrics']['macro_f1']:.4f}, "
            f"accuracy={best_config['metrics']['accuracy']:.4f}"
        )

        # Run detailed report for best config
        self.stdout.write("\n\nDetailed results for best configuration:")
        self._run_single(
            sentences,
            threshold=best_config['threshold'],
            min_words=best_config['min_words'],
        )

    def _run_single(self, sentences, threshold, min_words):
        """Run a single validation with detailed output."""
        self.stdout.write(f"\nInitializing ToneAnalyzer (threshold={threshold}, min_words={min_words})...")
        metrics = self._evaluate(sentences, threshold, min_words, show_progress=True)
        if metrics is None:
            self.stdout.write(self.style.ERROR("No sentences evaluated."))
            return

        total = metrics['total']
        correct = metrics['correct']
        accuracy = metrics['accuracy']

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("TONE CLASSIFIER VALIDATION RESULTS")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Dataset: SUBJ ({sentences[0]['metadata']['split']} split) — Pang & Lee, 2004")
        self.stdout.write(f"Samples: {total}")
        self.stdout.write(f"Model:   GroNLP/mdebertav3-subjectivity-english")
        self.stdout.write(f"Confidence threshold: {threshold}")
        self.stdout.write(f"Min words/sentence: {min_words}")
        self.stdout.write(f"Date:    {time.strftime('%Y-%m-%d')}")
        self.stdout.write(f"\nOverall Accuracy: {accuracy:.4f} ({correct}/{total})")

        self.stdout.write(f"\n{'Class':<15} {'Precision':>10} {'Recall':>10} {'F1':>10} {'Support':>10}")
        self.stdout.write("-" * 60)

        for class_name in ["objective", "subjective"]:
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
        self.stdout.write(f"{'':>20} {'Pred OBJ':>10} {'Pred SUBJ':>10}")
        self.stdout.write(f"{'Actual OBJ':>20} {cm[0][0]:>10} {cm[0][1]:>10}")
        self.stdout.write(f"{'Actual SUBJ':>20} {cm[1][0]:>10} {cm[1][1]:>10}")

        # Timing
        self.stdout.write(f"\nPerformance:")
        self.stdout.write(f"  Total time:  {metrics['total_time']:.2f}s")
        self.stdout.write(f"  Avg/sentence: {metrics['avg_time_ms']:.1f}ms")

        self.stdout.write("=" * 60)

    def _evaluate(self, sentences, threshold, min_words, show_progress=False):
        """Evaluate classifier with given parameters. Returns metrics dict."""
        analyzer = ToneAnalyzer(confidence_threshold=threshold, min_words=min_words)

        y_true = []
        y_pred = []
        correct = 0
        total = 0

        iterator = sentences
        if show_progress:
            iterator = tqdm(sentences, desc="Classifying")

        start_time = time.time()

        for doc_data in iterator:
            text = doc_data["primary_text"]
            gt_label = doc_data["reference_content"]["label"]

            result = analyzer.analyze(text)
            pred_label = 1 if result.subjectivity_ratio >= 0.5 else 0

            y_true.append(gt_label)
            y_pred.append(pred_label)

            if pred_label == gt_label:
                correct += 1
            total += 1

        elapsed = time.time() - start_time

        if total == 0:
            return None

        accuracy = correct / total

        # Per-class metrics
        classes = {"objective": 0, "subjective": 1}
        class_metrics = {}
        macro_p = macro_r = macro_f1 = 0.0

        for class_name, class_label in classes.items():
            tp = sum(1 for t, p in zip(y_true, y_pred) if t == class_label and p == class_label)
            fp = sum(1 for t, p in zip(y_true, y_pred) if t != class_label and p == class_label)
            fn = sum(1 for t, p in zip(y_true, y_pred) if t == class_label and p != class_label)
            support = sum(1 for t in y_true if t == class_label)

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

        # Confusion matrix
        cm = [[0, 0], [0, 0]]
        for t, p in zip(y_true, y_pred):
            cm[t][p] += 1

        return {
            'total': total,
            'correct': correct,
            'accuracy': accuracy,
            'macro_p': macro_p,
            'macro_r': macro_r,
            'macro_f1': macro_f1,
            'obj_recall': class_metrics['objective']['recall'],
            'subj_recall': class_metrics['subjective']['recall'],
            'confusion': cm,
            'total_time': elapsed,
            'avg_time_ms': (elapsed / total) * 1000,
            **class_metrics,
        }
