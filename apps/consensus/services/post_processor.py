"""
Post-processing layer for consensus nugget clusters.

Sits between deduplication and scoring in the pipeline:
  1. Cluster Merge    — LLM merges each cluster's raw members into one
                        maximally-informative representative.
  2. Tier Assignment  — LLM assigns tiers (1/2/3) to all merged facts.
  3. Theme Assignment — LLM groups facts into 5-8 named themes.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from django.conf import settings

from apps.extraction.services.llm_client import get_llm_client

from ..models import ConsensusNugget, ConsensusPool, Contradiction, RawNugget

logger = logging.getLogger(__name__)


# ─── Merge prompts ───────────────────────────────────────────────────────────

MERGE_SYSTEM_PROMPT = """\
You are a fact editor. You receive clusters of near-duplicate news facts \
extracted from different sources covering the same event. Each cluster contains \
variants of the same underlying fact.

For each cluster, produce ONE merged fact following these rules:

1. PRESERVE the most specific numbers, times, scores, and statistics from any variant. \
If one says "scored" and another says "scored with 7:42 left in the third period," keep the time.
2. PRESERVE proper nouns and full names. Never shorten "Ondrej Palat" to "Palat" if any variant \
has the full name.
3. COMBINE complementary details. If one variant has the score context ("gave Czechia a 3-2 lead") \
and another has the timing ("with 7:42 left"), the merged fact should include both.
4. KEEP attribution to non-press actors. If a variant says 'according to officials' or \
'the Pentagon said,' keep that — it's part of the fact.
5. STRIP attribution to news outlets. If a variant says "Wall Street Journal reported that X" \
or "according to Reuters, X" or "Bloomberg said X", the merged fact should be the underlying \
claim X — not the meta-claim about which outlet broke the story. Otherwise every other \
outlet covering the same story gets scored as "not supporting" the consensus claim even \
though they're reporting the same underlying fact.
6. Do NOT add information that isn't in any variant. Do NOT editorialize or interpret.
7. Do NOT start with "The." Write a direct declarative sentence.
8. One sentence only, 8-25 words. If combining details pushes past 25 words, keep the \
most specific version and drop the least informative detail.
9. If all variants say essentially the same thing with no complementary details, \
pick the most precise and complete wording verbatim."""

MERGE_USER_TEMPLATE = """\
Event: {topic_title}

Merge each cluster into one fact. Return ONLY a JSON array of strings, one per cluster, same order.

{clusters_block}"""


# ─── Contradiction prompts ───────────────────────────────────────────────────

CONTRADICTION_SYSTEM_PROMPT = """\
You are a fact-checker analyzing claims from multiple news sources about the same event. \
You receive clusters of near-duplicate news facts. Each cluster was grouped because the \
claims are semantically similar, but some may contain genuinely CONTRADICTORY claims.

For each cluster, determine if all members AGREE or if there are CONTRADICTIONS.

A contradiction means the claims are MUTUALLY EXCLUSIVE — both cannot be true at the same time.

AGREE (not contradictions):
- Synonyms or paraphrases: "agreement" vs "deal", "important" vs "more important" — AGREE.
- Different levels of detail: "talks in Pakistan" vs "talks in Islamabad, Pakistan" — AGREE.
- One has extra detail the other omits: "21-hour talks" vs "talks" — AGREE.
- Complementary facts: "fire at 3pm" vs "fire destroyed 2 buildings" — AGREE.
- Approximate vs exact: "about a dozen injured" vs "12 injured" — AGREE.
- Tense differences: "has met" vs "will meet" — AGREE.
- Name variants: "Zelenskyy" vs "Volodymyr Zelenskyy" — AGREE.

CONTRADICT (genuine contradictions):
- Different specific numbers for the SAME metric: "12 killed" vs "8 killed" — CONTRADICT.
- Opposite outcomes: "bill passed" vs "bill failed" — CONTRADICT.
- Directly opposing claims: "approved" vs "rejected", "ahead of" vs "after" — CONTRADICT.
- Different specific dates: "April 13" vs "April 14" — CONTRADICT.
- Mutually exclusive characterizations: "is weapons-grade" vs "is not weapons-grade" — CONTRADICT.

If some members are vague or ambiguous (e.g. a day name when others say specific dates), \
fold them into the most compatible group rather than making a separate group.

Output ONLY a JSON array of objects, one per cluster, same order:
[{{"status": "agree"}}, {{"status": "contradict", "groups": [[0, 2], [1, 3]], \
"explanation": "Reuters and AP say 12 killed while CNN and BBC say 8 killed"}}]

In "groups", list the 0-indexed member positions that agree with each other. \
Every member must appear in exactly one group. The first group should be the \
sub-group with more members (or alphabetically first source if tied).

In "explanation", refer to sources BY NAME (e.g. "Reuters", "WPLG") using the \
[Source Name] tags in each member line. Never use "Member 0" or "Source 2" — \
end users see this text and need readable source attribution."""

CONTRADICTION_USER_TEMPLATE = """\
Event: {topic_title}

Date reference (for resolving day names):
{date_reference}

Check each cluster for internal contradictions. Return a JSON array, one entry per cluster.

{clusters_block}"""


VERIFY_SYSTEM_PROMPT = """\
You are a strict fact verification expert. You are given pairs of claim texts \
that were flagged as potentially contradictory. Your job is to VERIFY whether \
the TWO CLAIM TEXTS THEMSELVES are mutually exclusive as written.

The cardinal rule: judge the visible text. A reader sees only the two claim \
texts you are given. Could a careful reader believe BOTH claims simultaneously? \
If yes, REJECT — no matter what reasoning a previous step gave for flagging it.

NOT contradictions (reject these):
- Identical-looking claims: "5.7 yards per carry" vs "5.7 yards per carry" — \
  even if the prompt context suggests an underlying disagreement, if both \
  visible texts say the same thing, REJECT.
- Tense differences: "was not a full participant" vs "has not been a full \
  participant" — REJECT.
- Different specificity, compatible content: "four-year contract extension" \
  vs "four-year, $64 million extension" — the second is a superset, both \
  can be true, REJECT.
- Synonyms or paraphrases: "agreement" vs "deal" — REJECT.
- Different detail levels: "Pakistan" vs "Islamabad, Pakistan" — REJECT.
- Name variants: "Zelenskyy" vs "Volodymyr Zelenskyy" — REJECT.
- Vague vs specific that could match: "Monday" vs "April 14" if Monday was \
  April 14 — REJECT.
- Complementary facts from the same list — REJECT.

REAL contradictions (confirm these) — the disagreement must be VISIBLE IN \
THE CLAIM TEXTS, not described in some prior explanation:
- Different specific numbers visible in both texts for the same metric: \
  "12 killed" vs "8 killed".
- Opposite outcomes visible in both texts: "passed" vs "failed".
- Directly opposing words visible in both texts: "approved" vs "rejected".
- Different specific dates visible in both texts: "April 13" vs "April 14".

For each pair, output "confirm" or "reject".
Output ONLY a JSON array of strings: ["confirm", "reject", "confirm", ...]"""

VERIFY_USER_TEMPLATE = """\
Event: {topic_title}

Date reference (for resolving day names):
{date_reference}

Verify each flagged contradiction. Are these genuinely mutually exclusive?

{pairs_block}"""


# ─── Tier prompts ────────────────────────────────────────────────────────────

TIER_SYSTEM_PROMPT = """\
You are a senior news editor assigning importance tiers to facts about a news event.

Tier 1 (Headline): The {tier1_target} most essential facts — final outcome, main result, the single \
biggest development. A reader who sees ONLY these facts should understand what happened.
Tier 2 (Context): ~{tier2_target} facts that explain how/why — key plays, significant \
figures, important consequences, timeline of events.
Tier 3 (Detail): Everything else — minor statistics, background color, quotes, \
historical parallels, peripheral storylines.

Rules:
- Assign EXACTLY {tier1_target} facts to Tier 1 (unless there are fewer than {tier1_target} total facts).
- Tier 2 should be approximately {tier2_target} facts, but use your judgment.
- Everything else is Tier 3.
- Source count is a signal (widely reported facts are more likely important) but not the only one. \
A fact reported by 2 sources can be Tier 1 if it's the core outcome.

Output ONLY a JSON array of integers (1, 2, or 3), one per input fact, in the same order."""

TIER_USER_TEMPLATE = """\
Event: {topic_title}

Facts:
{facts_block}

Assign a tier (1, 2, or 3) to each fact."""

RETIER_SYSTEM_PROMPT = """\
You are a senior news editor. You are given a list of candidate headline facts for a news event. \
Too many were selected. Pick exactly {tier1_target} that are the most essential — the facts a reader \
absolutely must know to understand what happened.

Output ONLY a JSON array of the selected fact numbers (1-indexed)."""

RETIER_USER_TEMPLATE = """\
Event: {topic_title}

Select exactly {tier1_target} headline facts from these candidates:
{candidates_block}"""


# ─── Theme prompts ──────────────────────────────────────────────────────────

THEME_SYSTEM_PROMPT = """\
You are a news editor organizing facts about an event into thematic groups.

Group the numbered facts into {min_themes}-{max_themes} themes. Each theme should have \
a short, descriptive name (2-5 words, e.g. "Legal Proceedings", "Community Response", \
"Financial Impact").

Rules:
- Every fact MUST be assigned to exactly one theme.
- Aim for {min_themes}-{max_themes} themes. Use fewer only if the facts are very uniform.
- Theme names should be specific to this event, not generic (prefer "Verdict & Damages" \
over "Legal").
- Order themes by importance: the most newsworthy theme first.

Output ONLY a JSON object with this structure:
{{"themes": [{{"name": "Theme Name", "facts": [1, 3, 7]}}, ...]}}
where "facts" contains the 1-indexed fact numbers."""

THEME_USER_TEMPLATE = """\
Event: {topic_title}

Facts:
{facts_block}

Group these facts into {min_themes}-{max_themes} named themes."""


# ─── Data classes ─────────────────────────────────────────────────────────────

def _build_date_reference():
    """Build a 3-week date-to-day mapping for the LLM."""
    from datetime import date, timedelta
    today = date.today()
    start = today - timedelta(days=7)
    lines = []
    for i in range(21):
        d = start + timedelta(days=i)
        marker = " (today)" if d == today else ""
        lines.append(f"{d.strftime('%A')} = {d.strftime('%B %d, %Y')}{marker}")
    return "\n".join(lines)


_INDEX_REF_RE = re.compile(
    r'\b(?:Members?|Sources?)\s+(\d+(?:\s*(?:,|and)\s*\d+)*)\b',
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")


def _substitute_source_indices(explanation: str, sources: list[str]) -> str:
    """Replace "Source 0", "Members 1 and 3" etc with actual source names.

    Belt-and-suspenders alongside the prompt instruction telling the LLM to
    use source names directly. If the LLM still emits "Source N" references,
    look up the corresponding source name and substitute it in.
    """
    if not explanation or not sources:
        return explanation

    def replace(match):
        idx_text = match.group(1)
        # Split on comma or "and"
        idx_parts = re.split(r'\s*(?:,|and)\s*', idx_text)
        names = []
        for part in idx_parts:
            try:
                i = int(part)
                if 0 <= i < len(sources):
                    names.append(sources[i])
            except ValueError:
                pass
        if not names:
            return match.group(0)
        if len(names) == 1:
            return names[0]
        if len(names) == 2:
            return f"{names[0]} and {names[1]}"
        return ", ".join(names[:-1]) + f", and {names[-1]}"

    return _INDEX_REF_RE.sub(replace, explanation)


def _token_jaccard(a: str, b: str) -> float:
    """Token-set Jaccard similarity of two strings (lowercased, alphanumeric)."""
    ta = set(_TOKEN_RE.findall(a.lower()))
    tb = set(_TOKEN_RE.findall(b.lower()))
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass
class PostProcessingResult:
    """Outcome of the full post-processing pass."""
    nuggets_merged: int
    tier1_count: int
    tier2_count: int
    tier3_count: int
    theme_count: int = 0
    contradictions_found: int = 0


# ─── Service ──────────────────────────────────────────────────────────────────

class NuggetPostProcessor:
    """
    LLM-based post-processing for consensus nuggets.

    Call process(pool) after deduplication and before scoring.
    """

    def __init__(self, backend: str | None = None):
        self.backend = backend or getattr(settings, 'LLM_BACKEND', 'deepseek')
        self.client = get_llm_client(self.backend)
        self.merge_batch_size = getattr(
            settings, 'CONSENSUS_MERGE_BATCH_SIZE', 30
        )
        self.tier1_target = getattr(settings, 'CONSENSUS_TIER1_TARGET', 5)
        self.tier2_target = getattr(settings, 'CONSENSUS_TIER2_TARGET', 15)

    def process(self, pool: ConsensusPool) -> PostProcessingResult:
        """Run merge (with contradiction check), tier assignment, then theme grouping."""
        nuggets_merged = self._merge_clusters(pool)
        tier1, tier2, tier3 = self._assign_tiers(pool)
        theme_count = self._assign_themes(pool)
        contradictions_found = pool.contradictions.count()

        return PostProcessingResult(
            nuggets_merged=nuggets_merged,
            tier1_count=tier1,
            tier2_count=tier2,
            tier3_count=tier3,
            theme_count=theme_count,
            contradictions_found=contradictions_found,
        )

    # ── Step 1: Merge ────────────────────────────────────────────────────────

    def _merge_clusters(self, pool: ConsensusPool) -> int:
        """
        LLM-merge multi-member clusters into single maximally-informative facts.

        Returns number of nuggets whose text was updated.
        """
        # Load consensus nuggets with their raw members
        nuggets = list(
            pool.nuggets
            .prefetch_related('raw_nuggets')
            .order_by('cluster_id')
        )

        if not nuggets:
            return 0

        # Identify multi-member clusters (worth merging)
        multi_member = []
        for cn in nuggets:
            raw_texts = list(cn.raw_nuggets.values_list('nugget_text', flat=True))
            if len(raw_texts) > 1:
                multi_member.append((cn, raw_texts))

        if not multi_member:
            logger.info("No multi-member clusters to merge")
            return 0

        # Check for contradictions before merging
        multi_member = self._check_contradictions(pool, multi_member)

        if not multi_member:
            logger.info("No multi-member clusters remain after contradiction check")
            return 0

        # Process in batches
        merged_count = 0
        for batch_start in range(0, len(multi_member), self.merge_batch_size):
            batch = multi_member[batch_start:batch_start + self.merge_batch_size]
            merged_count += self._merge_batch(pool, batch)

        return merged_count

    def _merge_batch(
        self,
        pool: ConsensusPool,
        batch: list[tuple[ConsensusNugget, list[str]]],
    ) -> int:
        """Merge a batch of clusters via a single LLM call."""
        # Build the clusters block
        cluster_lines = []
        for i, (cn, raw_texts) in enumerate(batch, 1):
            members = "\n".join(
                f'  {chr(96 + j)}) "{text}"'
                for j, text in enumerate(raw_texts, 1)
                if j <= 26  # safety: max 26 lettered items
            )
            cluster_lines.append(
                f"Cluster {i} ({cn.source_count} sources):\n{members}"
            )

        clusters_block = "\n\n".join(cluster_lines)

        user_prompt = MERGE_USER_TEMPLATE.format(
            topic_title=pool.topic.title,
            clusters_block=clusters_block,
        )

        try:
            response = self.client.generate(
                prompt=user_prompt,
                system=MERGE_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=4096,
            )
            merged_texts = self._parse_json_string_array(response, len(batch))
        except Exception as e:
            logger.warning(f"Merge LLM call failed, keeping originals: {e}")
            return 0

        # Apply merged texts
        updated = []
        for i, (cn, _raw_texts) in enumerate(batch):
            if i < len(merged_texts) and merged_texts[i]:
                cn.nugget_text = merged_texts[i]
                updated.append(cn)

        if updated:
            ConsensusNugget.objects.bulk_update(updated, ['nugget_text'])

        logger.debug(f"Merged {len(updated)}/{len(batch)} clusters in batch")
        return len(updated)

    # ── Contradiction detection ──────────────────────────────────────────────

    def _check_contradictions(
        self,
        pool: ConsensusPool,
        multi_member: list[tuple[ConsensusNugget, list[str]]],
    ) -> list[tuple[ConsensusNugget, list[str]]]:
        """
        LLM-check multi-member clusters for internal contradictions.

        Splits contradictory clusters into agreeing sub-groups, creating
        new ConsensusNuggets and Contradiction records as needed.

        Returns the updated multi_member list with contradictory clusters
        removed and their agreeing sub-groups re-added if still multi-member.
        """
        all_results = []
        for batch_start in range(0, len(multi_member), self.merge_batch_size):
            batch = multi_member[batch_start:batch_start + self.merge_batch_size]
            batch_results = self._check_contradiction_batch(pool, batch)
            all_results.extend(batch_results)

        surviving = []
        splits = 0
        for i, (cn, raw_texts) in enumerate(multi_member):
            if i >= len(all_results) or all_results[i] is None:
                surviving.append((cn, raw_texts))
                continue

            result = all_results[i]
            if result['status'] == 'agree':
                surviving.append((cn, raw_texts))
                continue

            # Contradictory cluster — split it
            new_nuggets = self._split_cluster(
                pool, cn, result['groups'],
                result.get('explanation', 'Conflicting claims detected.'),
            )
            splits += 1

            # Re-add sub-groups that still have multiple members
            for new_cn in new_nuggets:
                new_raw = list(
                    new_cn.raw_nuggets.values_list('nugget_text', flat=True)
                )
                if len(new_raw) > 1:
                    surviving.append((new_cn, new_raw))

        if splits:
            logger.info(f"Split {splits} contradictory clusters")

        return surviving

    def _check_contradiction_batch(
        self,
        pool: ConsensusPool,
        batch: list[tuple[ConsensusNugget, list[str]]],
    ) -> list[dict | None]:
        """Check a batch of clusters for contradictions via LLM."""
        cluster_lines = []
        # Per-cluster source names indexed the same way as the prompt's member ids
        cluster_source_names: list[list[str]] = []
        for i, (cn, _raw_texts) in enumerate(batch, 1):
            # Fetch raw nuggets with their source names, ordered by id (stable)
            raw_with_sources = list(
                cn.raw_nuggets
                .select_related('article__source')
                .order_by('id')
                .values_list('nugget_text', 'article__source__name')
            )
            cluster_source_names.append([src for (_, src) in raw_with_sources])
            members = "\n".join(
                f'  {j}) [{src}] "{text}"'
                for j, (text, src) in enumerate(raw_with_sources)
            )
            cluster_lines.append(
                f"Cluster {i} ({cn.source_count} sources):\n{members}"
            )

        clusters_block = "\n\n".join(cluster_lines)
        user_prompt = CONTRADICTION_USER_TEMPLATE.format(
            topic_title=pool.topic.title,
            date_reference=_build_date_reference(),
            clusters_block=clusters_block,
        )

        try:
            response = self.client.generate(
                prompt=user_prompt,
                system=CONTRADICTION_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=4096,
            )
            results = self._parse_contradiction_response(response, len(batch))
        except Exception as e:
            logger.warning(
                f"Contradiction check failed, assuming no contradictions: {e}"
            )
            return [None] * len(batch)

        # Post-process: rewrite any "Member N" / "Source N" references in the
        # explanation with the actual source name. Belt-and-suspenders alongside
        # the prompt instruction (the LLM still slips into index references).
        for cluster_idx, result in enumerate(results):
            if not result or result.get('status') != 'contradict':
                continue
            sources = cluster_source_names[cluster_idx]
            result['explanation'] = _substitute_source_indices(
                result.get('explanation', ''), sources
            )
        return results

    @classmethod
    def _parse_contradiction_response(
        cls, response: str, expected_count: int
    ) -> list[dict | None]:
        """Parse contradiction check response into list of results."""
        response = cls._clean_response(response)

        parsed = None
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        if not parsed or not isinstance(parsed, list):
            logger.warning(
                f"Could not parse contradiction response: {response[:200]}"
            )
            return [None] * expected_count

        results = []
        for item in parsed:
            if not isinstance(item, dict):
                results.append(None)
                continue
            status = item.get('status', 'agree')
            if status == 'agree':
                results.append({'status': 'agree'})
            elif status == 'contradict':
                groups = item.get('groups', [])
                explanation = item.get('explanation', '')
                if len(groups) >= 2:
                    results.append({
                        'status': 'contradict',
                        'groups': groups,
                        'explanation': explanation,
                    })
                else:
                    results.append(None)
            else:
                results.append(None)

        while len(results) < expected_count:
            results.append(None)
        return results[:expected_count]

    def _split_cluster(
        self,
        pool: ConsensusPool,
        original_cn: ConsensusNugget,
        groups: list[list[int]],
        explanation: str,
    ) -> list[ConsensusNugget]:
        """
        Split a contradictory ConsensusNugget into sub-groups.

        Group 0 (majority) keeps the original ConsensusNugget.
        Group 1+ become new ConsensusNuggets.
        Contradiction records link each pair (nugget_a = majority side).
        """
        raw_nuggets = list(
            original_cn.raw_nuggets
            .select_related('article__source')
            .order_by('id')
        )

        # Validate group indices
        all_indices = set()
        for group in groups:
            all_indices.update(group)
        if not all_indices or max(all_indices) >= len(raw_nuggets):
            logger.warning(
                f"Invalid group indices for cluster {original_cn.cluster_id}, "
                f"skipping split"
            )
            return [original_cn]

        group_nuggets = []
        for group_idx, member_indices in enumerate(groups):
            group_raw = [
                raw_nuggets[j] for j in member_indices
                if j < len(raw_nuggets)
            ]
            if not group_raw:
                continue

            group_sources = sorted(set(
                rn.article.source.name for rn in group_raw
            ))

            if group_idx == 0:
                # Update original nugget with group-0 data
                original_cn.nugget_text = group_raw[0].nugget_text
                original_cn.source_count = len(group_sources)
                original_cn.source_names = group_sources
                original_cn.save(update_fields=[
                    'nugget_text', 'source_count', 'source_names',
                ])
                for rn in group_raw:
                    rn.consensus_nugget = original_cn
                RawNugget.objects.bulk_update(group_raw, ['consensus_nugget'])
                group_nuggets.append(original_cn)
            else:
                new_cn = ConsensusNugget.objects.create(
                    pool=pool,
                    nugget_text=group_raw[0].nugget_text,
                    importance=original_cn.importance,
                    source_count=len(group_sources),
                    source_names=group_sources,
                    cluster_id=original_cn.cluster_id,
                )
                for rn in group_raw:
                    rn.consensus_nugget = new_cn
                RawNugget.objects.bulk_update(group_raw, ['consensus_nugget'])
                group_nuggets.append(new_cn)

        # Create Contradiction records — nugget_a = side with more sources
        for i in range(len(group_nuggets)):
            for j in range(i + 1, len(group_nuggets)):
                a, b = group_nuggets[i], group_nuggets[j]
                # Ensure nugget_a is the majority side
                if b.source_count > a.source_count:
                    a, b = b, a
                Contradiction.objects.create(
                    pool=pool, nugget_a=a, nugget_b=b,
                    explanation=explanation,
                )

        # Update pool nugget count
        pool.nugget_count = pool.nuggets.count()
        pool.save(update_fields=['nugget_count'])

        logger.info(
            f"Split cluster {original_cn.cluster_id} into "
            f"{len(group_nuggets)} sub-groups"
        )
        return group_nuggets

    def _verify_contradictions(self, pool: ConsensusPool) -> int:
        """
        Pass 2: Verify flagged contradictions via LLM.

        Removes false positives by asking the LLM to strictly confirm
        each contradiction. Deletes rejected Contradiction records and
        merges the nuggets back.
        """
        contradictions = list(
            pool.contradictions.select_related('nugget_a', 'nugget_b').all()
        )
        if not contradictions:
            return 0

        # Build pairs block for verification.
        # Deliberately omit the upstream "Flagged because" explanation — the
        # verifier should judge purely from the visible claim texts, not be
        # primed by the first pass's interpretation (which is what was letting
        # false positives like tense diffs and identical-looking texts slip
        # through).
        pairs = []
        for i, c in enumerate(contradictions, 1):
            pairs.append(
                f"Pair {i}:\n"
                f'  A) "{c.nugget_a.nugget_text}"\n'
                f'  B) "{c.nugget_b.nugget_text}"'
            )
        pairs_block = "\n\n".join(pairs)

        user_prompt = VERIFY_USER_TEMPLATE.format(
            topic_title=pool.topic.title,
            date_reference=_build_date_reference(),
            pairs_block=pairs_block,
        )

        try:
            response = self.client.generate(
                prompt=user_prompt,
                system=VERIFY_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=4096,
            )
            verdicts = self._parse_verify_response(response, len(contradictions))
        except Exception as e:
            logger.warning(f"Verification failed, keeping all contradictions: {e}")
            return len(contradictions)

        # Process verdicts — delete rejected contradictions.
        # Also apply a deterministic safety net: if the two claim texts are
        # near-identical (token-Jaccard > 0.85), reject even if the LLM
        # confirmed. Catches "5.7 ypc" vs "5.7 ypc"-style false positives
        # where the underlying nuggets differed but the merged display text
        # collapsed to identical wording.
        # Set high (0.85, not 0.7) so genuine short-claim contradictions
        # like "Stage 17 was 200 km" vs "Stage 17 was 202 km" (Jaccard ~0.71)
        # survive — they share a lot of vocabulary but the differing number
        # is real and reader-visible.
        verified = 0
        for i, c in enumerate(contradictions):
            llm_confirms = i < len(verdicts) and verdicts[i] == 'confirm'
            text_sim = _token_jaccard(
                c.nugget_a.nugget_text, c.nugget_b.nugget_text
            )
            too_similar = text_sim > 0.85

            if llm_confirms and not too_similar:
                verified += 1
            else:
                c.delete()
                logger.debug(
                    f"Rejected contradiction (llm={'confirm' if llm_confirms else 'reject'}, "
                    f"sim={text_sim:.2f}): {c.nugget_a.nugget_text[:40]} "
                    f"vs {c.nugget_b.nugget_text[:40]}"
                )

        return verified

    @classmethod
    def _parse_verify_response(
        cls, response: str, expected_count: int
    ) -> list[str]:
        """Parse verification response into list of 'confirm'/'reject'."""
        response = cls._clean_response(response)

        parsed = None
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            match = re.search(r'\[.*\]', response, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        if not parsed or not isinstance(parsed, list):
            logger.warning(f"Could not parse verify response: {response[:200]}")
            return ['confirm'] * expected_count  # default to keeping

        results = []
        for item in parsed:
            val = str(item).lower().strip()
            if 'confirm' in val:
                results.append('confirm')
            else:
                results.append('reject')

        while len(results) < expected_count:
            results.append('confirm')
        return results[:expected_count]

    # ── Step 2: Tier ─────────────────────────────────────────────────────────

    def _assign_tiers(
        self, pool: ConsensusPool
    ) -> tuple[int, int, int]:
        """
        LLM-assign importance tiers to all consensus nuggets.

        Returns (tier1_count, tier2_count, tier3_count).
        """
        nuggets = list(pool.nuggets.order_by('-source_count', 'id'))

        if not nuggets:
            return 0, 0, 0

        chunk_size = 200
        if len(nuggets) <= chunk_size:
            tiers = self._tier_chunk(pool, nuggets)
        else:
            tiers = self._tier_chunked(pool, nuggets, chunk_size)

        # Apply tiers
        updated = []
        for i, cn in enumerate(nuggets):
            if i < len(tiers):
                cn.tier = tiers[i]
            else:
                cn.tier = 3  # default untiered to detail
            updated.append(cn)

        ConsensusNugget.objects.bulk_update(updated, ['tier'])

        tier1 = sum(1 for t in tiers if t == 1)
        tier2 = sum(1 for t in tiers if t == 2)
        tier3 = len(nuggets) - tier1 - tier2

        logger.info(
            f"Tiered {len(nuggets)} nuggets: "
            f"{tier1} headline, {tier2} context, {tier3} detail"
        )
        return tier1, tier2, tier3

    def _tier_chunk(
        self,
        pool: ConsensusPool,
        nuggets: list[ConsensusNugget],
    ) -> list[int]:
        """Assign tiers to a single chunk of nuggets via LLM."""
        facts_block = "\n".join(
            f"[{i + 1}] {cn.nugget_text} ({cn.source_count} sources)"
            for i, cn in enumerate(nuggets)
        )

        system = TIER_SYSTEM_PROMPT.format(
            tier1_target=self.tier1_target,
            tier2_target=self.tier2_target,
        )
        user_prompt = TIER_USER_TEMPLATE.format(
            topic_title=pool.topic.title,
            facts_block=facts_block,
        )

        # Scale max_tokens: ~10 tokens per item, with headroom for reasoning
        tier_max_tokens = max(8192, len(nuggets) * 10 + 1024)

        try:
            response = self.client.generate(
                prompt=user_prompt,
                system=system,
                temperature=0.1,
                max_tokens=tier_max_tokens,
            )
            tiers = self._parse_tier_array(response, len(nuggets))
            # Sanity check: if tiering clearly failed (>95% tier 3), log warning
            tier3_pct = sum(1 for t in tiers if t == 3) / len(tiers)
            if tier3_pct > 0.95 and len(nuggets) > 20:
                logger.warning(
                    f"Tier response degenerate ({tier3_pct:.0%} tier-3), "
                    f"response length={len(response)}"
                )
            return tiers
        except Exception as e:
            logger.warning(f"Tier LLM call failed: {e}")
            return [3] * len(nuggets)

    def _tier_chunked(
        self,
        pool: ConsensusPool,
        nuggets: list[ConsensusNugget],
        chunk_size: int,
    ) -> list[int]:
        """Tier nuggets in chunks, then re-tier if too many tier-1 facts."""
        all_tiers = [3] * len(nuggets)

        for start in range(0, len(nuggets), chunk_size):
            chunk = nuggets[start:start + chunk_size]
            chunk_tiers = self._tier_chunk(pool, chunk)
            for i, tier in enumerate(chunk_tiers):
                if start + i < len(all_tiers):
                    all_tiers[start + i] = tier

        # Re-tier pass if too many tier-1 facts
        tier1_indices = [i for i, t in enumerate(all_tiers) if t == 1]
        max_tier1 = int(self.tier1_target * 1.5)

        if len(tier1_indices) > max_tier1:
            logger.info(
                f"Re-tiering: {len(tier1_indices)} tier-1 candidates "
                f"(target {self.tier1_target})"
            )
            all_tiers = self._retier_pass(
                pool, nuggets, all_tiers, tier1_indices
            )

        return all_tiers

    def _retier_pass(
        self,
        pool: ConsensusPool,
        nuggets: list[ConsensusNugget],
        all_tiers: list[int],
        tier1_indices: list[int],
    ) -> list[int]:
        """Re-tier tier-1 candidates to select exactly tier1_target."""
        candidates_block = "\n".join(
            f"[{j + 1}] {nuggets[i].nugget_text} ({nuggets[i].source_count} sources)"
            for j, i in enumerate(tier1_indices)
        )

        system = RETIER_SYSTEM_PROMPT.format(tier1_target=self.tier1_target)
        user_prompt = RETIER_USER_TEMPLATE.format(
            topic_title=pool.topic.title,
            tier1_target=self.tier1_target,
            candidates_block=candidates_block,
        )

        try:
            response = self.client.generate(
                prompt=user_prompt,
                system=system,
                temperature=0.1,
                max_tokens=1024,
            )
            selected = self._parse_selected_indices(
                response, len(tier1_indices)
            )
        except Exception as e:
            logger.warning(f"Re-tier LLM call failed: {e}")
            # Fallback: keep top N by source_count
            sorted_candidates = sorted(
                tier1_indices,
                key=lambda i: nuggets[i].source_count,
                reverse=True,
            )
            selected = set(range(1, self.tier1_target + 1))
            # Map back: selected refers to 1-indexed positions in candidates
            keep_indices = set(sorted_candidates[:self.tier1_target])
            for i in tier1_indices:
                if i not in keep_indices:
                    all_tiers[i] = 2
            return all_tiers

        # Apply: demote non-selected tier-1 candidates to tier 2
        selected_original_indices = set()
        for sel_num in selected:
            if 1 <= sel_num <= len(tier1_indices):
                selected_original_indices.add(tier1_indices[sel_num - 1])

        for i in tier1_indices:
            if i not in selected_original_indices:
                all_tiers[i] = 2

        return all_tiers

    # ── Step 3: Theme ─────────────────────────────────────────────────────────

    def _assign_themes(self, pool: ConsensusPool) -> int:
        """
        LLM-assign thematic groups to consensus nuggets.

        Only themes tier 1 & 2 nuggets (the ones users actually see).
        Returns number of themes created.
        """
        nuggets = list(
            pool.nuggets
            .order_by('tier', '-source_count', 'id')
        )

        if not nuggets:
            return 0

        # Build numbered fact list for the LLM
        facts_block = "\n".join(
            f"[{i + 1}] {cn.nugget_text} ({cn.source_count} sources)"
            for i, cn in enumerate(nuggets)
        )

        num_nuggets = len(nuggets)
        min_themes = max(3, min(5, num_nuggets // 3))
        max_themes = min(8, max(min_themes, num_nuggets // 2))

        system = THEME_SYSTEM_PROMPT.format(
            min_themes=min_themes,
            max_themes=max_themes,
        )
        user_prompt = THEME_USER_TEMPLATE.format(
            topic_title=pool.topic.title,
            facts_block=facts_block,
            min_themes=min_themes,
            max_themes=max_themes,
        )

        try:
            response = self.client.generate(
                prompt=user_prompt,
                system=system,
                temperature=0.2,
                max_tokens=8192,
            )
            themes = self._parse_theme_response(response, num_nuggets)
        except Exception as e:
            logger.warning(f"Theme LLM call failed: {e}")
            return 0

        if not themes:
            return 0

        # Apply themes to nuggets
        updated = []
        for order, theme_group in enumerate(themes, 1):
            name = theme_group['name']
            for fact_idx in theme_group['facts']:
                if 0 <= fact_idx < len(nuggets):
                    nuggets[fact_idx].theme = name
                    nuggets[fact_idx].theme_order = order
                    updated.append(nuggets[fact_idx])

        # Assign unthemed nuggets to a catch-all
        themed_ids = {cn.id for cn in updated}
        for cn in nuggets:
            if cn.id not in themed_ids:
                cn.theme = 'Other Details'
                cn.theme_order = len(themes) + 1
                updated.append(cn)

        if updated:
            ConsensusNugget.objects.bulk_update(
                updated, ['theme', 'theme_order']
            )

        logger.info(
            f"Assigned {len(themes)} themes to {len(updated)} nuggets"
        )
        return len(themes)

    @classmethod
    def _parse_theme_response(
        cls, response: str, num_facts: int
    ) -> list[dict] | None:
        """
        Parse LLM theme response into list of
        [{"name": str, "facts": [0-indexed ints]}, ...].
        """
        response = cls._clean_response(response)

        # Try to extract JSON object
        parsed = None
        try:
            parsed = json.loads(response)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        if not parsed or not isinstance(parsed, dict):
            logger.warning(
                f"Could not parse theme response: {response[:200]}..."
            )
            return None

        raw_themes = parsed.get('themes', [])
        if not isinstance(raw_themes, list) or not raw_themes:
            return None

        # Convert 1-indexed fact numbers to 0-indexed
        themes = []
        for item in raw_themes:
            if not isinstance(item, dict):
                continue
            name = str(item.get('name', '')).strip()
            facts = item.get('facts', [])
            if not name or not facts:
                continue
            indices = []
            for f in facts:
                try:
                    idx = int(f) - 1  # 1-indexed → 0-indexed
                    if 0 <= idx < num_facts:
                        indices.append(idx)
                except (ValueError, TypeError):
                    pass
            if indices:
                themes.append({'name': name, 'facts': indices})

        return themes if themes else None

    # ── Parsing helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _clean_response(response: str) -> str:
        """Strip thinking tags and whitespace from LLM response."""
        response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
        return response.strip()

    @classmethod
    def _parse_json_string_array(
        cls, response: str, expected_count: int
    ) -> list[str]:
        """
        Parse LLM response into a list of strings (for merge step).

        Falls back gracefully: returns partial results padded with empty
        strings for missing positions.
        """
        response = cls._clean_response(response)

        # Try direct JSON parse
        try:
            parsed = json.loads(response)
            if isinstance(parsed, list):
                result = [str(item) for item in parsed]
                # Pad if short
                while len(result) < expected_count:
                    result.append('')
                return result[:expected_count]
        except json.JSONDecodeError:
            pass

        # Try regex extraction
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    result = [str(item) for item in parsed]
                    while len(result) < expected_count:
                        result.append('')
                    return result[:expected_count]
            except json.JSONDecodeError:
                pass

        logger.warning(
            f"Could not parse merge response as JSON array. "
            f"Response: {response[:200]}..."
        )
        return [''] * expected_count

    @classmethod
    def _parse_tier_array(
        cls, response: str, expected_count: int
    ) -> list[int]:
        """
        Parse LLM response into a list of tier integers (1, 2, or 3).

        Falls back to tier 3 for unparseable positions.
        """
        response = cls._clean_response(response)

        # Try direct JSON parse
        try:
            parsed = json.loads(response)
            if isinstance(parsed, list):
                return cls._convert_tiers(parsed, expected_count)
        except json.JSONDecodeError:
            pass

        # Try regex extraction
        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    return cls._convert_tiers(parsed, expected_count)
            except json.JSONDecodeError:
                pass

        # Line-by-line fallback: look for digits 1/2/3
        tiers = []
        for line in response.split('\n'):
            line = line.strip()
            if not line:
                continue
            # Look for a standalone digit 1, 2, or 3
            digit_match = re.search(r'\b([123])\b', line)
            if digit_match:
                tiers.append(int(digit_match.group(1)))

        if tiers:
            while len(tiers) < expected_count:
                tiers.append(3)
            return tiers[:expected_count]

        logger.warning(
            f"Could not parse tier response. "
            f"Response: {response[:200]}..."
        )
        return [3] * expected_count

    @staticmethod
    def _convert_tiers(raw: list, expected_count: int) -> list[int]:
        """Convert raw parsed values to valid tier integers."""
        tiers = []
        for item in raw:
            try:
                val = int(item)
                tiers.append(val if val in (1, 2, 3) else 3)
            except (ValueError, TypeError):
                tiers.append(3)

        while len(tiers) < expected_count:
            tiers.append(3)
        return tiers[:expected_count]

    @classmethod
    def _parse_selected_indices(
        cls, response: str, candidate_count: int
    ) -> set[int]:
        """Parse re-tier response into a set of 1-indexed selected positions."""
        response = cls._clean_response(response)

        # Try JSON array of ints
        try:
            parsed = json.loads(response)
            if isinstance(parsed, list):
                return {
                    int(x) for x in parsed
                    if 1 <= int(x) <= candidate_count
                }
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        match = re.search(r'\[.*\]', response, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    return {
                        int(x) for x in parsed
                        if 1 <= int(x) <= candidate_count
                    }
            except (json.JSONDecodeError, ValueError, TypeError):
                pass

        # Fallback: extract all numbers from response
        numbers = re.findall(r'\b(\d+)\b', response)
        return {
            int(n) for n in numbers
            if 1 <= int(n) <= candidate_count
        }
