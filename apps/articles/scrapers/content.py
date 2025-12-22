"""Article content extraction using trafilatura."""

import logging
from typing import Dict, Any
from datetime import datetime

import trafilatura
from trafilatura.settings import use_config

logger = logging.getLogger(__name__)


class ContentExtractor:
    """Extract article content using trafilatura."""

    def __init__(self):
        self.config = use_config()
        self.config.set("DEFAULT", "EXTRACTION_TIMEOUT", "30")
        self.config.set("DEFAULT", "MIN_OUTPUT_SIZE", "100")

    def extract(self, url: str, html: str = None) -> Dict[str, Any]:
        """Extract article content from URL or pre-fetched HTML."""
        result = {
            'title': '',
            'author': '',
            'date': None,
            'content': '',
            'summary': '',
        }

        try:
            # Fetch if HTML not provided
            if html is None:
                downloaded = trafilatura.fetch_url(url)
                if not downloaded:
                    logger.warning(f"Failed to download {url}")
                    return result
            else:
                downloaded = html

            # Extract with metadata
            extracted = trafilatura.extract(
                downloaded,
                url=url,
                include_comments=False,
                include_tables=False,
                include_images=False,
                include_links=False,
                output_format='txt',
                config=self.config,
            )

            if extracted:
                result['content'] = extracted

            # Get metadata separately for more detail
            metadata = trafilatura.extract_metadata(downloaded)
            if metadata:
                result['title'] = metadata.title or ''
                result['author'] = metadata.author or ''
                result['summary'] = metadata.description or ''

                # Parse date
                if metadata.date:
                    try:
                        from dateutil import parser as date_parser
                        result['date'] = date_parser.parse(metadata.date)
                    except (ValueError, TypeError):
                        pass

            if not result['summary'] and result['content']:
                result['summary'] = self._generate_summary(result['content'])

        except Exception as e:
            logger.error(f"Extraction failed for {url}: {e}")

        return result

    def _generate_summary(self, content: str, max_length: int = 300) -> str:
        """Generate a simple summary from content."""
        if not content:
            return ''

        # Take first paragraph or sentences
        paragraphs = content.split('\n\n')
        if paragraphs:
            first_para = paragraphs[0].strip()
            if len(first_para) <= max_length:
                return first_para
            # Truncate at sentence boundary
            sentences = first_para.split('. ')
            summary = ''
            for sentence in sentences:
                if len(summary) + len(sentence) + 2 <= max_length:
                    summary += sentence + '. '
                else:
                    break
            return summary.strip()

        return content[:max_length].rsplit(' ', 1)[0] + '...'

    def extract_batch(self, urls: list) -> Dict[str, Dict[str, Any]]:
        """Extract content from multiple URLs."""
        results = {}
        for url in urls:
            results[url] = self.extract(url)
        return results
