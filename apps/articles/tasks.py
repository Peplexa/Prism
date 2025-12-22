"""Celery tasks for article scraping and processing."""

import logging
from celery import shared_task, chain
from django.utils import timezone

from .models import Source, Article
from .scrapers import RSSScraper, SitemapScraper, HomepageScraper, ContentExtractor

logger = logging.getLogger(__name__)


def get_scraper_for_source(source: Source):
    """Get the appropriate scraper based on source discovery method."""
    scrapers = {
        Source.DiscoveryMethod.RSS: RSSScraper,
        Source.DiscoveryMethod.SITEMAP: SitemapScraper,
        Source.DiscoveryMethod.HOMEPAGE: HomepageScraper,
    }
    scraper_class = scrapers.get(source.discovery_method)
    if scraper_class:
        return scraper_class(source)
    return None


@shared_task(bind=True)
def scrape_all_sources(self):
    """Master task: scrape all active sources."""
    active_sources = Source.objects.filter(is_active=True)
    count = 0

    for source in active_sources:
        scrape_source.delay(source.id)
        count += 1

    logger.info(f"Queued scraping for {count} sources")
    return f"Queued {count} sources"


@shared_task(bind=True, max_retries=3)
def scrape_source(self, source_id: int):
    """Scrape articles from a single source."""
    try:
        source = Source.objects.get(id=source_id)
    except Source.DoesNotExist:
        logger.error(f"Source {source_id} not found")
        return

    scraper = get_scraper_for_source(source)
    if not scraper:
        logger.error(f"No scraper available for {source.name}")
        return

    try:
        # Discover articles
        discovered = scraper.discover_articles()
        new_count = 0

        for article_data in discovered:
            if Article.objects.filter(url=article_data.url).exists():
                continue

            article = Article.objects.create(
                source=source,
                url=article_data.url,
                title=(article_data.title or '')[:500],
                summary=(article_data.summary or '')[:500],
                author=(article_data.author or '')[:300],
                published_at=article_data.published_at,
                status=Article.ProcessingStatus.PENDING,
            )

            # Queue content extraction
            extract_article_content.delay(article.id)
            new_count += 1

        # Update last scraped timestamp
        source.last_scraped_at = timezone.now()
        source.save(update_fields=['last_scraped_at'])

        logger.info(f"Scraped {source.name}: {new_count} new articles")
        return f"{source.name}: {new_count} new articles"

    except Exception as e:
        logger.error(f"Error scraping {source.name}: {e}")
        raise self.retry(exc=e, countdown=60 * 5)  # Retry in 5 minutes


@shared_task(bind=True, max_retries=3)
def extract_article_content(self, article_id: int):
    """Extract full article content from URL."""
    try:
        article = Article.objects.get(id=article_id)
    except Article.DoesNotExist:
        logger.error(f"Article {article_id} not found")
        return

    try:
        extractor = ContentExtractor()
        content = extractor.extract(article.url)

        # Update article with extracted content
        if content['content']:
            article.content = content['content']
            article.status = Article.ProcessingStatus.SCRAPED

            # Update metadata if better than what we have
            if content['title'] and not article.title:
                article.title = content['title'][:500]
            if content['author'] and not article.author:
                article.author = content['author'][:300]
            if content['summary'] and not article.summary:
                article.summary = content['summary'][:500]
            if content['date'] and not article.published_at:
                article.published_at = content['date']

            article.save()

            from apps.topics.tasks import generate_article_embedding
            generate_article_embedding.delay(article.id)
            return f"Extracted {article.word_count} words"

        else:
            article.status = Article.ProcessingStatus.FAILED
            article.error_message = "No content extracted"
            article.save()
            return "No content extracted"

    except Exception as e:
        article.status = Article.ProcessingStatus.FAILED
        article.error_message = str(e)[:500]
        article.save()
        logger.error(f"Error extracting article {article_id}: {e}")
        raise self.retry(exc=e, countdown=60)


@shared_task
def cleanup_failed_articles(days_old: int = 7):
    """Remove failed articles older than N days."""
    from datetime import timedelta
    cutoff = timezone.now() - timedelta(days=days_old)

    deleted, _ = Article.objects.filter(
        status=Article.ProcessingStatus.FAILED,
        created_at__lt=cutoff
    ).delete()

    logger.info(f"Cleaned up {deleted} failed articles")
    return f"Deleted {deleted} failed articles"
