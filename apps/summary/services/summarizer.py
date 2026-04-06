"""Neutral summary generation from consensus facts."""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps.consensus.models import ConsensusPool, ConsensusNugget
from apps.extraction.services.llm_client import get_llm_client
from apps.topics.models import Topic
from ..models import NeutralSummary

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_PROMPT = """You are a neutral news editor writing a factual summary of a news event.

You are given verified facts about this event, extracted from multiple news sources and organized \
by importance tier:
- Tier 1 (Headline): Essential what-happened facts reported by most sources
- Tier 2 (Context): Important supporting details and consequences
- Tier 3 (Detail): Peripheral facts — incorporate selectively

Write a clear, neutral, factual summary that:
1. Opens with Tier 1 facts as the core narrative
2. Incorporates Tier 2 facts to explain context and consequences
3. Selectively uses Tier 3 facts only if they materially add detail
4. Uses objective, dispassionate language -- no opinion, no editorial framing
5. Attributes claims where appropriate ("according to...", "officials said...")
6. Does NOT speculate or infer beyond the provided facts
7. Is 2-4 paragraphs long

Write ONLY the summary text. No preamble, no headings, no bullet points."""

SUMMARY_SYSTEM_PROMPT_LEGACY = """You are a neutral news editor writing a factual summary of a news event.

You are given a set of verified facts (nuggets) about this event, extracted from multiple news sources.
Each fact has an importance level: "vital" facts were reported by 3+ sources, "okay" facts by fewer.

Write a clear, neutral, factual summary that:
1. Prioritizes vital facts (reported by multiple sources)
2. Uses objective, dispassionate language -- no opinion, no editorial framing
3. Attributes claims where appropriate ("according to...", "officials said...")
4. Organizes information logically (what happened, who was involved, consequences)
5. Does NOT speculate or infer beyond the provided facts
6. Is 2-4 paragraphs long

Write ONLY the summary text. No preamble, no headings, no bullet points."""

SUMMARY_USER_TEMPLATE = """Event: {topic_title}

Verified Facts (sorted by importance):
{nuggets_text}

Write a neutral, factual summary of this event based on the facts above."""


class NeutralSummarizer:
    """Generates a neutral summary from consensus nuggets using an LLM."""

    def __init__(self, backend: str = 'deepseek'):
        self.backend = backend

    def generate(self, topic_id: int, regenerate: bool = False) -> NeutralSummary:
        """
        Generate a neutral summary for a topic.

        Args:
            topic_id: ID of the topic to summarize.
            regenerate: If True, delete existing summary and regenerate.

        Returns:
            NeutralSummary instance.
        """
        topic = Topic.objects.get(id=topic_id)

        # Check for existing summary
        try:
            existing = topic.neutral_summary
            if not regenerate:
                return existing
            existing.delete()
        except NeutralSummary.DoesNotExist:
            pass

        # Require a completed consensus pool
        try:
            pool = topic.consensus_pool
        except ConsensusPool.DoesNotExist:
            raise ValueError(f"Topic {topic_id} has no consensus pool")

        if pool.status != ConsensusPool.Status.COMPLETE:
            raise ValueError(
                f"Consensus pool for topic {topic_id} is {pool.status}, not complete"
            )

        summary = NeutralSummary.objects.create(
            topic=topic,
            status=NeutralSummary.Status.GENERATING,
        )

        try:
            nuggets = list(pool.nuggets.order_by('-source_count', 'id'))

            if not nuggets:
                summary.status = NeutralSummary.Status.FAILED
                summary.error_message = 'No consensus nuggets available'
                summary.save()
                return summary

            has_tiers = any(n.tier is not None for n in nuggets)
            nuggets_text = self._format_nuggets(nuggets)
            system_prompt = (
                SUMMARY_SYSTEM_PROMPT if has_tiers
                else SUMMARY_SYSTEM_PROMPT_LEGACY
            )

            client = get_llm_client(self.backend)
            response = client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": SUMMARY_USER_TEMPLATE.format(
                        topic_title=topic.title,
                        nuggets_text=nuggets_text,
                    )},
                ],
                temperature=0.3,
                max_tokens=1024,
            )

            summary.summary_text = response.strip()
            summary.nuggets_used = len(nuggets)
            summary.model_name = getattr(
                settings, 'DEEPSEEK_MODEL', 'deepseek-chat'
            )
            summary.status = NeutralSummary.Status.COMPLETE
            summary.generated_at = timezone.now()
            summary.save()

        except Exception as e:
            logger.error(f"Summary generation failed for topic {topic_id}: {e}")
            summary.status = NeutralSummary.Status.FAILED
            summary.error_message = str(e)[:1000]
            summary.save()
            raise

        return summary

    @staticmethod
    def _format_nuggets(nuggets: list[ConsensusNugget]) -> str:
        """Format nuggets grouped by tier, falling back to importance for untiered pools."""
        has_tiers = any(n.tier is not None for n in nuggets)

        if has_tiers:
            tier_labels = {1: 'HEADLINE FACTS', 2: 'CONTEXT FACTS', 3: 'DETAIL FACTS'}
            lines = []
            for tier_num in (1, 2, 3):
                tier_nuggets = [n for n in nuggets if n.tier == tier_num]
                # Untiered nuggets (legacy/failed post-processing) go in context
                if tier_num == 2:
                    tier_nuggets += [n for n in nuggets if n.tier is None]
                if tier_nuggets:
                    lines.append(f"\n--- {tier_labels[tier_num]} ---")
                    for n in tier_nuggets:
                        sources_str = ", ".join(n.source_names[:5])
                        lines.append(f"- {n.nugget_text} (Sources: {sources_str})")
            return "\n".join(lines)
        else:
            lines = []
            for n in nuggets:
                tag = "[VITAL]" if n.importance == ConsensusNugget.Importance.VITAL else "[OKAY]"
                sources_str = ", ".join(n.source_names[:5])
                lines.append(f"- {tag} {n.nugget_text} (Sources: {sources_str})")
            return "\n".join(lines)
