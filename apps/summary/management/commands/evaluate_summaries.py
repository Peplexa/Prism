"""
Evaluate neutral summary quality using LLM-as-judge.

Rates each summary on 4 criteria (factuality, neutrality, coherence,
completeness) using a 1-5 scale, then reports aggregate statistics.

Usage:
    python manage.py evaluate_summaries --all --sync
    python manage.py evaluate_summaries --topic-id 1 --sync
"""

from django.core.management.base import BaseCommand

from apps.consensus.models import ConsensusNugget
from apps.summary.models import NeutralSummary
from apps.summary.services.evaluator import SummaryEvaluator


class Command(BaseCommand):
    help = "Evaluate neutral summary quality using LLM-as-judge"

    def add_arguments(self, parser):
        parser.add_argument('--topic-id', type=int, help='Evaluate summary for a specific topic')
        parser.add_argument('--all', action='store_true', help='Evaluate all completed summaries')
        parser.add_argument('--sync', action='store_true', help='Run synchronously (required)')
        parser.add_argument('--limit', type=int, default=50, help='Max summaries to evaluate')

    def handle(self, *args, **options):
        if not options['sync']:
            self.stderr.write("Only synchronous mode supported. Use --sync.")
            return

        evaluator = SummaryEvaluator(backend='deepseek')

        if options['topic_id']:
            summaries = NeutralSummary.objects.filter(
                topic_id=options['topic_id'],
                status=NeutralSummary.Status.COMPLETE,
            )
        elif options['all']:
            summaries = NeutralSummary.objects.filter(
                status=NeutralSummary.Status.COMPLETE,
            )[:options['limit']]
        else:
            self.stderr.write("Specify --topic-id <ID> or --all")
            return

        summaries = list(summaries.select_related('topic'))
        if not summaries:
            self.stderr.write("No completed summaries found.")
            return

        self.stdout.write(f"Evaluating {len(summaries)} summaries...\n")

        results = []
        for summary in summaries:
            self.stdout.write(f"  Evaluating: {summary.topic.title[:60]}...")

            # Load consensus nuggets for this summary
            try:
                pool = summary.topic.consensus_pool
            except Exception:
                self.stderr.write(f"    No consensus pool found, skipping.")
                continue

            nuggets = list(pool.nuggets.order_by('-source_count', 'id'))
            if not nuggets:
                self.stderr.write(f"    No nuggets found, skipping.")
                continue

            nuggets_text = self._format_nuggets(nuggets)

            try:
                score = evaluator.evaluate(
                    summary_text=summary.summary_text,
                    nuggets_text=nuggets_text,
                    topic_title=summary.topic.title,
                )
                results.append({
                    'topic': summary.topic.title,
                    'score': score,
                })
                self.stdout.write(
                    f"    F={score.factuality} N={score.neutrality} "
                    f"Co={score.coherence} Cm={score.completeness} "
                    f"→ {score.rating} ({score.average:.2f})"
                )
            except Exception as e:
                self.stderr.write(f"    FAILED: {e}")

        if not results:
            self.stderr.write("No summaries were successfully evaluated.")
            return

        # Aggregate statistics
        self._print_report(results)

    def _format_nuggets(self, nuggets: list) -> str:
        """Format nuggets as a bulleted list with importance tags."""
        lines = []
        for n in nuggets:
            tag = "[VITAL]" if n.importance == ConsensusNugget.Importance.VITAL else "[OKAY]"
            sources_str = ", ".join(n.source_names[:5])
            lines.append(f"- {tag} {n.nugget_text} (Sources: {sources_str})")
        return "\n".join(lines)

    def _print_report(self, results):
        """Print aggregate evaluation report."""
        n = len(results)

        avg_fact = sum(r['score'].factuality for r in results) / n
        avg_neut = sum(r['score'].neutrality for r in results) / n
        avg_cohe = sum(r['score'].coherence for r in results) / n
        avg_comp = sum(r['score'].completeness for r in results) / n
        avg_overall = sum(r['score'].average for r in results) / n

        excellent = sum(1 for r in results if r['score'].rating == 'Excellent')
        good = sum(1 for r in results if r['score'].rating == 'Good')
        fair = sum(1 for r in results if r['score'].rating == 'Fair')
        poor = sum(1 for r in results if r['score'].rating == 'Poor')

        good_or_excellent = excellent + good
        pct_good = (good_or_excellent / n) * 100

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("NEUTRAL SUMMARY QUALITY EVALUATION")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Summaries evaluated: {n}")
        self.stdout.write(f"Evaluator: DeepSeek API (LLM-as-judge, temperature=0.0)")

        self.stdout.write(f"\nPer-Criterion Averages (1-5 scale):")
        self.stdout.write(f"  Factuality:   {avg_fact:.2f}")
        self.stdout.write(f"  Neutrality:   {avg_neut:.2f}")
        self.stdout.write(f"  Coherence:    {avg_cohe:.2f}")
        self.stdout.write(f"  Completeness: {avg_comp:.2f}")
        self.stdout.write(f"  Overall:      {avg_overall:.2f}")

        self.stdout.write(f"\nRating Distribution:")
        self.stdout.write(f"  Excellent (avg>=4.5): {excellent}/{n} ({excellent/n*100:.0f}%)")
        self.stdout.write(f"  Good (avg>=3.5):      {good}/{n} ({good/n*100:.0f}%)")
        self.stdout.write(f"  Fair (avg>=2.5):      {fair}/{n} ({fair/n*100:.0f}%)")
        self.stdout.write(f"  Poor (avg<2.5):       {poor}/{n} ({poor/n*100:.0f}%)")

        self.stdout.write(f"\nGood or Excellent: {good_or_excellent}/{n} ({pct_good:.0f}%)")

        target_met = "YES" if pct_good >= 80 else "NO"
        self.stdout.write(f"Target (>=80% Good/Excellent): {target_met}")

        # Per-summary details
        self.stdout.write(f"\nPer-Summary Scores:")
        self.stdout.write(f"{'Topic':<40} {'F':>3} {'N':>3} {'Co':>3} {'Cm':>3} {'Avg':>5} {'Rating':<10}")
        self.stdout.write("-" * 70)
        for r in results:
            s = r['score']
            title = r['topic'][:38]
            self.stdout.write(
                f"{title:<40} {s.factuality:>3} {s.neutrality:>3} "
                f"{s.coherence:>3} {s.completeness:>3} {s.average:>5.2f} {s.rating:<10}"
            )

        self.stdout.write("=" * 60)
