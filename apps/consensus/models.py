"""Models for consensus fact pool and omission scoring."""

from django.db import models

from apps.core.models import TimestampedModel


def _bias_class(known_bias):
    """Map Source.BiasRating to simple left/center/right."""
    if known_bias in ('far_left', 'left', 'center_left'):
        return 'left'
    elif known_bias in ('far_right', 'right', 'center_right'):
        return 'right'
    return 'center'


class ConsensusPool(TimestampedModel):
    """
    A consensus fact pool for a topic (event).

    Aggregates and deduplicates nuggets extracted from all articles
    covering the same event, then scores each article's coverage.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        EXTRACTING = 'extracting', 'Extracting Nuggets'
        DEDUPLICATING = 'deduplicating', 'Deduplicating'
        POST_PROCESSING = 'post_processing', 'Post-Processing'
        SCORING = 'scoring', 'Scoring Articles'
        COMPLETE = 'complete', 'Complete'
        FAILED = 'failed', 'Failed'

    topic = models.OneToOneField(
        'topics.Topic',
        on_delete=models.CASCADE,
        related_name='consensus_pool',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    articles_processed = models.IntegerField(default=0)
    nugget_count = models.IntegerField(default=0)
    vital_nugget_count = models.IntegerField(default=0)
    model_name = models.CharField(max_length=100, blank=True)
    similarity_threshold = models.FloatField(default=0.85)
    built_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    # Pre-computed report data (omission, tone, framing, matrix)
    # Built after pool completion so the report view avoids heavy queries.
    report_cache = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-built_at']

    def __str__(self):
        return f"Pool for {self.topic.title[:40]} ({self.status})"

    def build_report_cache(self):
        """Pre-compute all data needed by TopicReportView and store as JSON."""
        from apps.articles.models import Article
        from apps.analysis.models import ArticleAnalysis
        from apps.consensus.services.pool_builder import compute_scores

        topic = self.topic

        # --- Omission data ---
        scores = list(
            self.scores
            .filter(coverage_score__isnull=False)
            .select_related('article__source')
            .order_by('-coverage_score')
        )
        omission_data = []
        score_source_map = {}  # score.id → source_name (for matrix)
        for score in scores:
            src = score.article.source
            weighted = compute_scores(
                score.support_count, score.partial_support_count,
                score.not_support_count, score.total_nuggets,
                score.vital_support_count, score.vital_partial_support_count,
                score.vital_total,
            )['weighted_coverage_score']
            score_source_map[score.id] = src.name
            omission_data.append({
                'source_name': src.name,
                'bias': _bias_class(src.known_bias),
                'coverage_pct': round(score.coverage_score * 100),
                'weighted_coverage_pct': round(weighted * 100),
            })

        # --- Source articles with analysis (exclude wire copies) ---
        articles = list(
            Article.objects.filter(cluster__topic=topic, is_wire_content=False)
            .select_related('source', 'analysis')
            .order_by('source__name', '-published_at')
        )

        tone_data = []
        framing_data = []
        for article in articles:
            try:
                analysis = article.analysis
                if analysis.status != 'complete':
                    continue
            except ArticleAnalysis.DoesNotExist:
                continue

            bias = _bias_class(article.source.known_bias)

            if analysis.subjectivity_ratio is not None:
                tone_data.append({
                    'source_name': article.source.name,
                    'bias': bias,
                    'subjectivity_pct': round(analysis.subjectivity_ratio * 100),
                    'tone_label': analysis.tone_label,
                })

            if analysis.leaning_left is not None:
                framing_data.append({
                    'source_name': article.source.name,
                    'bias': bias,
                    'left_pct': round(analysis.leaning_left * 100),
                    'center_pct': round(analysis.leaning_center * 100),
                    'right_pct': round(analysis.leaning_right * 100),
                    'dominant_leaning': analysis.dominant_leaning,
                })

        tone_data.sort(key=lambda x: x['subjectivity_pct'])

        # --- Source summary table ---
        source_lookup = {}
        for item in omission_data:
            source_lookup[item['source_name']] = {
                'source_name': item['source_name'],
                'bias': item['bias'],
                'coverage_pct': item['coverage_pct'],
                'weighted_coverage_pct': item['weighted_coverage_pct'],
                'subjectivity_pct': None,
                'tone_label': None,
                'dominant_leaning': None,
                'left_pct': None,
                'center_pct': None,
                'right_pct': None,
            }
        for item in tone_data:
            if item['source_name'] in source_lookup:
                source_lookup[item['source_name']]['subjectivity_pct'] = item['subjectivity_pct']
                source_lookup[item['source_name']]['tone_label'] = item['tone_label']
        for item in framing_data:
            if item['source_name'] in source_lookup:
                entry = source_lookup[item['source_name']]
                entry['dominant_leaning'] = item['dominant_leaning']
                entry['left_pct'] = item['left_pct']
                entry['center_pct'] = item['center_pct']
                entry['right_pct'] = item['right_pct']
        source_summary = sorted(
            source_lookup.values(),
            key=lambda x: -(x['weighted_coverage_pct'] or 0),
        )

        # --- Consensus nuggets ---
        all_nuggets = list(self.nuggets.order_by(
            'theme_order', 'tier', '-source_count', 'id'
        ))
        nuggets_data = [
            {
                'id': n.id,
                'text': n.nugget_text,
                'importance': n.importance,
                'tier': n.tier,
                'source_count': n.source_count,
                'theme': n.theme,
                'theme_order': n.theme_order,
            }
            for n in all_nuggets
        ]

        # --- Fact matrix ---
        judgment_rows = (
            NuggetJudgment.objects
            .filter(score__pool=self)
            .values_list('score_id', 'consensus_nugget_id', 'label')
        )
        matrix_data = {}
        scored_source_names = []
        for score_id, nug_id, label in judgment_rows:
            src_name = score_source_map.get(score_id, '')
            if src_name not in scored_source_names:
                scored_source_names.append(src_name)
            nug_key = str(nug_id)
            if nug_key not in matrix_data:
                matrix_data[nug_key] = {}
            matrix_data[nug_key][src_name] = label

        self.report_cache = {
            'omission_data': omission_data,
            'tone_data': tone_data,
            'framing_data': framing_data,
            'source_summary': source_summary,
            'nuggets': nuggets_data,
            'matrix_data': matrix_data,
            'matrix_sources': scored_source_names,
        }
        self.save(update_fields=['report_cache'])


class ConsensusNugget(TimestampedModel):
    """
    A deduplicated fact in the consensus pool.

    Represents a cluster of semantically similar raw nuggets
    from multiple articles/sources.
    """

    class Importance(models.TextChoices):
        VITAL = 'vital', 'Vital'
        OKAY = 'okay', 'Okay'

    pool = models.ForeignKey(
        ConsensusPool,
        on_delete=models.CASCADE,
        related_name='nuggets',
    )
    nugget_text = models.TextField()
    importance = models.CharField(
        max_length=10,
        choices=Importance.choices,
        default=Importance.OKAY,
        db_index=True,
    )
    tier = models.IntegerField(
        null=True,
        blank=True,
        choices=[(1, 'Headline'), (2, 'Context'), (3, 'Detail')],
        db_index=True,
    )
    theme = models.CharField(max_length=100, blank=True, default='')
    theme_order = models.IntegerField(default=0)
    source_count = models.IntegerField(default=1)
    source_names = models.JSONField(default=list)
    cluster_id = models.IntegerField(default=0)

    class Meta:
        ordering = ['theme_order', 'tier', '-source_count', 'cluster_id']

    def __str__(self):
        label = self.nugget_text[:60]
        return f"[{self.importance}] {label} ({self.source_count} sources)"


class RawNugget(TimestampedModel):
    """
    A raw nugget extracted from a single article, before deduplication.

    Links to the ConsensusNugget it was merged into after clustering.
    """

    pool = models.ForeignKey(
        ConsensusPool,
        on_delete=models.CASCADE,
        related_name='raw_nuggets',
    )
    article = models.ForeignKey(
        'articles.Article',
        on_delete=models.CASCADE,
        related_name='raw_nuggets',
    )
    nugget_text = models.TextField()
    nugget_type = models.CharField(max_length=100, blank=True)
    consensus_nugget = models.ForeignKey(
        ConsensusNugget,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='raw_nuggets',
    )

    class Meta:
        ordering = ['article', 'id']

    def __str__(self):
        return f"{self.article.source.name}: {self.nugget_text[:50]}"


class OmissionScore(TimestampedModel):
    """
    Omission score for a single article against the consensus pool.

    Measures what percentage of consensus facts the article covers.
    """

    pool = models.ForeignKey(
        ConsensusPool,
        on_delete=models.CASCADE,
        related_name='scores',
    )
    article = models.ForeignKey(
        'articles.Article',
        on_delete=models.CASCADE,
        related_name='omission_scores',
    )
    # Overall metrics
    omission_rate = models.FloatField(null=True, blank=True)
    vital_omission_rate = models.FloatField(null=True, blank=True)
    coverage_score = models.FloatField(null=True, blank=True)
    # Counts
    support_count = models.IntegerField(default=0)
    partial_support_count = models.IntegerField(default=0)
    not_support_count = models.IntegerField(default=0)
    total_nuggets = models.IntegerField(default=0)
    vital_support_count = models.IntegerField(default=0)
    vital_partial_support_count = models.IntegerField(default=0)
    vital_total = models.IntegerField(default=0)
    # Meta
    scored_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        unique_together = ['pool', 'article']
        ordering = ['-coverage_score']
        indexes = [
            models.Index(fields=['pool', '-coverage_score']),
        ]

    def __str__(self):
        if self.coverage_score is not None:
            return (
                f"{self.article.source.name}: "
                f"coverage={self.coverage_score:.0%}"
            )
        return f"{self.article.source.name}: pending"

    @property
    def weighted_coverage_score(self):
        """Importance-weighted coverage: vital facts weighted more heavily."""
        from apps.consensus.services.pool_builder import compute_scores
        if self.total_nuggets == 0:
            return 1.0
        scores = compute_scores(
            self.support_count,
            self.partial_support_count,
            self.not_support_count,
            self.total_nuggets,
            self.vital_support_count,
            self.vital_partial_support_count,
            self.vital_total,
        )
        return scores['weighted_coverage_score']


class NuggetJudgment(TimestampedModel):
    """
    Per-nugget judgment for a specific article.

    Records whether a consensus nugget is supported, partially
    supported, or not supported by the article.
    """

    class Label(models.TextChoices):
        SUPPORT = 'support', 'Support'
        PARTIAL_SUPPORT = 'partial_support', 'Partial Support'
        NOT_SUPPORT = 'not_support', 'Not Support'

    score = models.ForeignKey(
        OmissionScore,
        on_delete=models.CASCADE,
        related_name='judgments',
    )
    consensus_nugget = models.ForeignKey(
        ConsensusNugget,
        on_delete=models.CASCADE,
        related_name='judgments',
    )
    label = models.CharField(
        max_length=20,
        choices=Label.choices,
    )

    class Meta:
        unique_together = ['score', 'consensus_nugget']

    def __str__(self):
        return f"{self.consensus_nugget.nugget_text[:40]} → {self.label}"
