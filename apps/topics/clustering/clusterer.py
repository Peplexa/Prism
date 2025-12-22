"""Article clustering using Agglomerative Clustering with cosine similarity."""

import logging
from typing import List, Dict, Any, Optional
from collections import Counter

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import AgglomerativeClustering

from django.conf import settings
from django.utils.text import slugify

logger = logging.getLogger(__name__)


class ArticleClusterer:
    """Cluster articles into topics using Agglomerative Clustering."""

    def __init__(
        self,
        min_cluster_size: int = None,
        min_sources: int = None,
        similarity_threshold: float = None,
        min_article_similarity: float = None,
    ):
        self.min_cluster_size = min_cluster_size or getattr(
            settings, 'CLUSTERING_MIN_CLUSTER_SIZE', 2
        )
        self.min_sources = min_sources or getattr(
            settings, 'CLUSTERING_MIN_SOURCES', 2
        )
        self.similarity_threshold = similarity_threshold or getattr(
            settings, 'CLUSTERING_SIMILARITY_THRESHOLD', 0.50
        )
        self.min_article_similarity = min_article_similarity or getattr(
            settings, 'CLUSTERING_MIN_ARTICLE_SIMILARITY', 0.50
        )

    def cluster(self, articles) -> List[Dict[str, Any]]:
        """Cluster articles into topics based on embedding similarity."""
        # Convert to list if queryset
        articles = list(articles)

        if len(articles) < self.min_cluster_size:
            return []

        # Extract embeddings and filter out articles without embeddings
        valid_articles = []
        embeddings = []

        for article in articles:
            if article.embedding:
                valid_articles.append(article)
                embeddings.append(article.embedding)

        if len(valid_articles) < self.min_cluster_size:
            return []

        embeddings = np.array(embeddings)

        # Compute cosine similarity and convert to distance
        similarity_matrix = cosine_similarity(embeddings)
        # Convert similarity to distance (1 - similarity)
        distance_matrix = 1 - similarity_matrix

        # Run Agglomerative Clustering with distance threshold
        # distance_threshold = 1 - similarity_threshold
        clusterer = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=1 - self.similarity_threshold,
            metric='precomputed',
            linkage='average',
        )

        cluster_labels = clusterer.fit_predict(distance_matrix)

        # Calculate confidence based on average similarity to cluster centroid
        probabilities = np.ones(len(valid_articles))

        # Group articles by cluster
        clusters_dict = {}
        for idx, (article, label, prob) in enumerate(
            zip(valid_articles, cluster_labels, probabilities)
        ):
            if label not in clusters_dict:
                clusters_dict[label] = []

            clusters_dict[label].append({
                'article': article,
                'confidence': float(prob),
                'index': idx,
            })

        # Remove outlier articles that don't meet minimum similarity to cluster
        clusters_dict = self._remove_outliers(clusters_dict, similarity_matrix)

        # Filter out clusters smaller than min_cluster_size
        clusters_dict = {
            label: articles
            for label, articles in clusters_dict.items()
            if len(articles) >= self.min_cluster_size
        }

        # Filter out clusters with fewer than min_sources different sources
        # (single-source clusters aren't useful for bias comparison)
        if self.min_sources > 1:
            filtered_dict = {}
            for label, articles in clusters_dict.items():
                source_ids = set(a['article'].source_id for a in articles)
                if len(source_ids) >= self.min_sources:
                    filtered_dict[label] = articles
            clusters_dict = filtered_dict

        # Convert to output format
        clusters = []
        for label, cluster_articles in clusters_dict.items():
            # Sort by confidence
            cluster_articles.sort(key=lambda x: x['confidence'], reverse=True)

            # Extract keywords from titles
            titles = [a['article'].title for a in cluster_articles]
            keywords = self._extract_keywords(titles)

            # Generate topic title from top keywords or highest confidence article
            if keywords:
                topic_title = self._generate_title(keywords, titles, cluster_articles)
            else:
                topic_title = cluster_articles[0]['article'].title[:100]

            # Create slug
            base_slug = slugify(topic_title)[:150]

            clusters.append({
                'title': topic_title,
                'slug': base_slug,
                'keywords': keywords[:10],
                'articles': [
                    {
                        'id': a['article'].id,
                        'confidence': a['confidence'],
                        'rank': rank,
                    }
                    for rank, a in enumerate(cluster_articles)
                ]
            })

        logger.info(f"Found {len(clusters)} clusters from {len(valid_articles)} articles")
        return clusters

    def _remove_outliers(
        self,
        clusters_dict: Dict[int, List[Dict]],
        similarity_matrix: np.ndarray,
    ) -> Dict[int, List[Dict]]:
        """Remove articles below min_article_similarity threshold."""
        filtered_clusters = {}

        for label, articles in clusters_dict.items():
            if len(articles) <= 1:
                # Single article clusters - keep as is (will be filtered later by min_cluster_size)
                filtered_clusters[label] = articles
                continue

            # Get indices of articles in this cluster
            indices = [a['index'] for a in articles]

            # Check each article
            kept_articles = []
            for article in articles:
                idx = article['index']
                # Find max similarity to any other article in the cluster
                max_sim = 0.0
                for other_idx in indices:
                    if other_idx != idx:
                        sim = similarity_matrix[idx, other_idx]
                        max_sim = max(max_sim, sim)

                if max_sim >= self.min_article_similarity:
                    article['confidence'] = float(max_sim)
                    kept_articles.append(article)

            if kept_articles:
                filtered_clusters[label] = kept_articles

        return filtered_clusters

    def _extract_keywords(self, titles: List[str], top_n: int = 10) -> List[str]:
        """Extract keywords from article titles using TF-IDF."""
        if not titles:
            return []

        try:
            # Use TF-IDF to find important terms
            vectorizer = TfidfVectorizer(
                max_features=100,
                stop_words='english',
                ngram_range=(1, 2),
                min_df=1,
                max_df=0.9,
            )

            tfidf_matrix = vectorizer.fit_transform(titles)
            feature_names = vectorizer.get_feature_names_out()

            # Sum TF-IDF scores across documents
            scores = np.asarray(tfidf_matrix.sum(axis=0)).flatten()

            # Get top keywords
            top_indices = scores.argsort()[-top_n:][::-1]
            keywords = [feature_names[i] for i in top_indices]

            return keywords

        except Exception as e:
            logger.warning(f"Error extracting keywords: {e}")
            # Fallback: extract common words
            all_words = ' '.join(titles).lower().split()
            word_counts = Counter(all_words)
            # Remove common stop words
            stop_words = {'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for', 'of', 'and', 'is', 'are'}
            keywords = [
                word for word, count in word_counts.most_common(top_n + len(stop_words))
                if word not in stop_words and len(word) > 2
            ][:top_n]
            return keywords

    def _generate_title(self, keywords: List[str], titles: List[str], articles=None) -> str:
        """Pick the best title from the cluster."""
        import re

        if not titles:
            return "Unnamed Topic"

        # Prefixes to strip
        prefix_pattern = r'^(watch|video|breaking|update|live|opinion|analysis|exclusive|explained):\s*'

        # Patterns to penalize
        bad_patterns = [r'\?$', r'^(why|how|what|when|where|who)\s', r'(slams|blasts|destroys)']

        def score(title: str) -> float:
            s = 0.0
            lower = title.lower()
            # Prefer titles with keywords
            s += sum(0.5 for kw in keywords[:5] if kw.lower() in lower)
            # Prefer medium length
            if 40 <= len(title) <= 80:
                s += 1.0
            # Penalize bad patterns
            for p in bad_patterns:
                if re.search(p, title, re.IGNORECASE):
                    s -= 0.5
            return s

        cleaned = [(re.sub(prefix_pattern, '', t, flags=re.IGNORECASE).strip(), t) for t in titles]
        best = max(cleaned, key=lambda x: score(x[0]))
        return best[0][:100]
