"""Generate embeddings for articles using sentence-transformers."""

import logging
from typing import List
import numpy as np

from django.conf import settings

logger = logging.getLogger(__name__)

# Lazy load the model to avoid loading on import
_model = None


def get_model():
    """Get or initialize the sentence transformer model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        model_name = getattr(settings, 'EMBEDDING_MODEL', 'all-MiniLM-L6-v2')
        logger.info(f"Loading embedding model: {model_name}")
        _model = SentenceTransformer(model_name)
    return _model


class EmbeddingGenerator:
    """Generate embeddings for text using sentence-transformers."""

    def __init__(self):
        """Initialize the embedding generator."""
        self.model = get_model()

    def generate(self, text: str) -> np.ndarray:
        """
        Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Numpy array of embedding vector
        """
        if not text:
            # Return zero vector for empty text
            return np.zeros(self.model.get_sentence_embedding_dimension())

        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding

    def generate_batch(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """
        Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed
            batch_size: Batch size for encoding

        Returns:
            Numpy array of shape (len(texts), embedding_dim)
        """
        if not texts:
            return np.array([])

        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            show_progress_bar=len(texts) > 100,
        )
        return embeddings

    def prepare_article_text(self, article) -> str:
        """
        Prepare article text for embedding.

        Combines title and content snippet for better semantic representation.

        Args:
            article: Article model instance

        Returns:
            Combined text string
        """
        parts = []

        if article.title:
            parts.append(article.title)

        # Use summary if available, otherwise first part of content
        if article.summary:
            parts.append(article.summary)
        elif article.content:
            # Take first ~500 chars of content
            content_preview = article.content[:500]
            if len(article.content) > 500:
                # Try to break at word boundary
                content_preview = content_preview.rsplit(' ', 1)[0]
            parts.append(content_preview)

        return '. '.join(parts)
