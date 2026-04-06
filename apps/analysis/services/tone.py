"""
Tone (subjectivity) analysis service.

Uses the GroNLP/mdebertav3-subjectivity-english HuggingFace classifier
to classify each sentence as objective or subjective, then computes
the subjectivity ratio for the article.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logger = logging.getLogger(__name__)

MODEL_NAME = 'GroNLP/mdebertav3-subjectivity-english'

# Module-level cache so the model is loaded once per process
_model = None
_tokenizer = None


def _get_model_and_tokenizer():
    global _model, _tokenizer
    if _model is None:
        logger.info("Loading tone model: %s", MODEL_NAME)
        _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        _model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
        _model.eval()
    return _model, _tokenizer


# Simple sentence splitter — splits on .!? followed by whitespace + uppercase
_SENT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\u201c])')


@dataclass
class ToneResult:
    subjectivity_ratio: float   # 0.0 = objective, 1.0 = subjective
    sentence_count: int
    subjective_count: int
    avg_confidence: float


class ToneAnalyzer:
    """Sentence-level subjectivity using GroNLP/mdebertav3-subjectivity-english."""

    def __init__(self, backend: str | None = None):
        # backend param kept for API compat but ignored — always uses HF model
        pass

    def analyze(self, text: str) -> ToneResult:
        """Analyze text for subjectivity by classifying each sentence."""
        if not text or not text.strip():
            return ToneResult(
                subjectivity_ratio=0.0,
                sentence_count=0,
                subjective_count=0,
                avg_confidence=0.0,
            )

        model, tokenizer = _get_model_and_tokenizer()

        sentences = self._split_sentences(text)
        if not sentences:
            return ToneResult(
                subjectivity_ratio=0.0,
                sentence_count=0,
                subjective_count=0,
                avg_confidence=0.0,
            )

        subjective_count = 0
        confidences = []
        batch_size = 32

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

                # Determine which label index is "subjective"
                subj_idx = None
                for idx, label in model.config.id2label.items():
                    if label.upper() in ('SUBJECTIVE', 'SUB'):
                        subj_idx = idx
                        break
                if subj_idx is None:
                    # Fallback: assume label 1 is subjective
                    subj_idx = 1

                for j in range(len(batch)):
                    subj_prob = probs[j][subj_idx].item()
                    is_subjective = subj_prob > 0.5
                    confidence = subj_prob if is_subjective else (1.0 - subj_prob)
                    confidences.append(confidence)
                    if is_subjective:
                        subjective_count += 1

            except Exception as e:
                logger.warning("Tone batch failed: %s", e)

        sentence_count = len(sentences)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0

        return ToneResult(
            subjectivity_ratio=round(subjective_count / sentence_count, 4) if sentence_count else 0.0,
            sentence_count=sentence_count,
            subjective_count=subjective_count,
            avg_confidence=round(avg_conf, 4),
        )

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentences, filtering out very short fragments."""
        raw = _SENT_RE.split(text.strip())
        # Keep sentences with at least 5 words
        return [s.strip() for s in raw if len(s.split()) >= 5]
