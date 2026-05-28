"""
Framing (political leaning) analysis service.

Uses the matous-volf/political-leaning-politics HuggingFace classifier
on each sentence individually, then averages scores across all sentences
for stable left/center/right probabilities.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logger = logging.getLogger(__name__)

MODEL_NAME = 'matous-volf/political-leaning-politics'
TOKENIZER_NAME = 'launch/POLITICS'

# Module-level cache so the model is loaded once per process
_model = None
_tokenizer = None
_lock = __import__('threading').Lock()

# Simple sentence splitter — splits on .!? followed by whitespace + uppercase
_SENT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\u201c])')


def _get_model_and_tokenizer():
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer
    with _lock:
        if _model is None:
            logger.info("Loading framing model: %s", MODEL_NAME)
            _tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_NAME)
            _model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
            _model.eval()
    return _model, _tokenizer


@dataclass
class FramingResult:
    left: float
    center: float
    right: float
    chunks_analyzed: int


class FramingAnalyzer:
    """Sentence-level political leaning using matous-volf/political-leaning-politics."""

    DEFAULT_MARGIN = 0.1

    @staticmethod
    def classify(
        left: float,
        center: float,
        right: float,
        margin_threshold: float = 0.1,
    ) -> str:
        """Classify political leaning with margin-based center detection."""
        from apps.analysis.utils import classify_leaning
        return classify_leaning(left, center, right, margin_threshold)

    def __init__(self, backend: str | None = None):
        # backend param kept for API compat but ignored — always uses HF model
        pass

    def analyze(self, text: str) -> FramingResult:
        """Analyze article text for political leaning sentence-by-sentence."""
        if not text or not text.strip():
            return FramingResult(left=0.0, center=0.0, right=0.0, chunks_analyzed=0)

        model, tokenizer = _get_model_and_tokenizer()
        sentences = self._split_sentences(text)

        if not sentences:
            return FramingResult(left=0.0, center=0.0, right=0.0, chunks_analyzed=0)

        all_probs = []
        batch_size = 32

        # Model labels: determine index mapping once
        labels = model.config.id2label

        for i in range(0, len(sentences), batch_size):
            batch = sentences[i:i + batch_size]
            try:
                inputs = tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors='pt',
                )
                with torch.no_grad():
                    outputs = model(**inputs)
                    probs = torch.softmax(outputs.logits, dim=-1)
                    all_probs.append(probs)
            except Exception as e:
                logger.warning("Framing batch failed: %s", e)

        if not all_probs:
            raise ValueError("All framing batches failed")

        # Concatenate all batches and average across sentences
        all_probs = torch.cat(all_probs, dim=0)
        avg_probs = all_probs.mean(dim=0)

        # Model labels may be 'left'/'center'/'right' or generic 'LABEL_0' etc.
        # Known mapping for matous-volf/political-leaning-politics:
        #   0 = left, 1 = center, 2 = right
        LABEL_MAP = {0: 'left', 1: 'center', 2: 'right'}

        scores = {}
        for idx, prob in enumerate(avg_probs.tolist()):
            label = labels.get(idx, '').lower()
            if label in ('left', 'center', 'right'):
                scores[label] = prob
            else:
                scores[LABEL_MAP.get(idx, f'label_{idx}')] = prob

        return FramingResult(
            left=round(scores.get('left', 0.0), 4),
            center=round(scores.get('center', 0.0), 4),
            right=round(scores.get('right', 0.0), 4),
            chunks_analyzed=int(all_probs.shape[0]),
        )

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentences, filtering out very short fragments."""
        raw = _SENT_RE.split(text.strip())
        return [s.strip() for s in raw if len(s.split()) >= 5]
