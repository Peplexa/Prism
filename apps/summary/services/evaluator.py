"""
LLM-as-judge evaluation for neutral summaries.

Uses DeepSeek API to rate each summary on a 4-criterion rubric:
factuality, neutrality, coherence, and completeness.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from apps.extraction.services.llm_client import get_llm_client

logger = logging.getLogger(__name__)


@dataclass
class EvaluationScore:
    factuality: int       # 1-5
    neutrality: int       # 1-5
    coherence: int        # 1-5
    completeness: int     # 1-5
    explanations: dict    # per-criterion explanation text

    @property
    def average(self) -> float:
        return (self.factuality + self.neutrality + self.coherence + self.completeness) / 4.0

    @property
    def rating(self) -> str:
        avg = self.average
        if avg >= 4.5:
            return 'Excellent'
        elif avg >= 3.5:
            return 'Good'
        elif avg >= 2.5:
            return 'Fair'
        else:
            return 'Poor'


EVAL_SYSTEM_PROMPT = """You are a quality evaluator for news summaries. You assess neutral summaries generated from consensus facts extracted across multiple news sources.

Rate the summary on four criteria using a 1-5 scale:

**Factuality** (Are claims grounded in the provided facts?)
5 = Every claim is directly supported by the provided facts
4 = Nearly all claims supported, minor inferences are reasonable
3 = Most claims supported but some unsupported statements
2 = Several claims lack factual basis
1 = Significant fabrication or hallucination

**Neutrality** (Is the language free of opinion, editorial framing, loaded language?)
5 = Entirely neutral, dispassionate, no opinion or slant
4 = Mostly neutral with very minor subjective phrasing
3 = Generally neutral but some opinionated or loaded language
2 = Noticeable bias or editorial tone
1 = Strongly opinionated or partisan

**Coherence** (Is the summary well-organized and easy to follow?)
5 = Excellent flow, logical structure, easy to read
4 = Well-organized with minor awkwardness
3 = Adequate but could be better organized
2 = Disjointed or hard to follow in places
1 = Incoherent or poorly structured

**Completeness** (Does it cover the vital facts proportionally?)
5 = All vital facts covered, good prioritization
4 = Most vital facts covered, minor omissions
3 = Some vital facts missing but core message clear
2 = Significant vital facts missing
1 = Fails to cover the main points

Return your evaluation as JSON with this exact format:
{
  "factuality": <1-5>,
  "neutrality": <1-5>,
  "coherence": <1-5>,
  "completeness": <1-5>,
  "explanations": {
    "factuality": "<brief explanation>",
    "neutrality": "<brief explanation>",
    "coherence": "<brief explanation>",
    "completeness": "<brief explanation>"
  }
}

Return ONLY the JSON. No other text."""

EVAL_USER_TEMPLATE = """Evaluate the following neutral summary.

Event: {topic_title}

Consensus Facts Used to Generate the Summary:
{nuggets_text}

Summary to Evaluate:
{summary_text}

Rate the summary on factuality, neutrality, coherence, and completeness (1-5 each).
Return only JSON."""


class SummaryEvaluator:
    """Evaluates neutral summaries using LLM-as-judge."""

    def __init__(self, backend: str = 'deepseek'):
        self.backend = backend

    def evaluate(
        self,
        summary_text: str,
        nuggets_text: str,
        topic_title: str,
    ) -> EvaluationScore:
        """Evaluate a single summary against its source nuggets."""
        client = get_llm_client(self.backend)

        prompt = EVAL_USER_TEMPLATE.format(
            topic_title=topic_title,
            nuggets_text=nuggets_text,
            summary_text=summary_text,
        )

        response = client.generate(
            prompt=prompt,
            system=EVAL_SYSTEM_PROMPT,
            temperature=0.0,
        )

        return self._parse_response(response)

    def _parse_response(self, response: str) -> EvaluationScore:
        """Parse LLM response into EvaluationScore."""
        # Clean up response — remove thinking tags if present (DeepSeek R1)
        response = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL)
        response = response.strip()

        # Try direct JSON parse
        try:
            data = json.loads(response)
            return self._build_score(data)
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in response
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return self._build_score(data)
            except json.JSONDecodeError:
                pass

        logger.warning(f"Could not parse evaluation response: {response[:200]}...")
        return EvaluationScore(
            factuality=3, neutrality=3, coherence=3, completeness=3,
            explanations={'error': 'Failed to parse LLM response'},
        )

    def _build_score(self, data: dict) -> EvaluationScore:
        """Build EvaluationScore from parsed JSON dict."""
        def clamp(val, lo=1, hi=5):
            try:
                return max(lo, min(hi, int(val)))
            except (TypeError, ValueError):
                return 3

        return EvaluationScore(
            factuality=clamp(data.get('factuality', 3)),
            neutrality=clamp(data.get('neutrality', 3)),
            coherence=clamp(data.get('coherence', 3)),
            completeness=clamp(data.get('completeness', 3)),
            explanations=data.get('explanations', {}),
        )
