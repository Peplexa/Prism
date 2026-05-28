"""Celery tasks for fetching events and articles from Event Registry."""

import logging
import os
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from .models import Source, Article
from apps.topics.models import Topic, ArticleCluster

logger = logging.getLogger(__name__)


def _download_topic_image(url: str, slug: str) -> str:
    """Download an image URL and save locally. Returns the static path, or '' on failure."""
    try:
        import httpx
        resp = httpx.get(url, timeout=10, follow_redirects=True)
        if resp.status_code != 200 or not resp.content:
            return ''

        ct = resp.headers.get('content-type', '')
        ext = 'jpg'
        if 'png' in ct:
            ext = 'png'
        elif 'webp' in ct:
            ext = 'webp'

        img_dir = os.path.join(settings.BASE_DIR, 'static', 'images', 'topics')
        os.makedirs(img_dir, exist_ok=True)

        filename = f'{slug[:50]}.{ext}'
        filepath = os.path.join(img_dir, filename)
        with open(filepath, 'wb') as f:
            f.write(resp.content)

        return f'/static/images/topics/{filename}'
    except Exception as e:
        logger.warning(f"Failed to download topic image from {url[:80]}: {e}")
        return ''


def _get_or_create_topic(event_data):
    """
    Get or create a Topic from Event Registry event data.

    Returns (topic, created) tuple. Returns (None, False) if
    the event data is missing required fields.
    """
    event_uri = event_data.get("uri", "")
    if not event_uri:
        return None, False

    # Return existing topic if we already have this event
    existing = Topic.objects.filter(event_registry_uri=event_uri).first()
    if existing:
        return existing, False

    # Extract event metadata
    lang = "eng"
    title_data = event_data.get("title", {})
    title = title_data.get(lang, "") if isinstance(title_data, dict) else str(title_data)
    if not title:
        return None, False

    summary_data = event_data.get("summary", {})
    summary = summary_data.get(lang, "") if isinstance(summary_data, dict) else str(summary_data)

    # Extract keywords from concepts
    concepts = event_data.get("concepts", [])
    keywords = [
        c.get("label", {}).get(lang, "")
        for c in concepts[:10]
        if c.get("label", {}).get(lang, "")
    ]

    # Create topic with unique slug
    base_slug = slugify(title)[:180]
    slug = base_slug
    counter = 1
    while Topic.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1

    topic = Topic.objects.create(
        title=title[:300],
        slug=slug,
        description=summary[:1000] if summary else "",
        keywords=keywords,
        event_registry_uri=event_uri,
    )

    return topic, True


@shared_task(bind=True, max_retries=3)
def fetch_events(self):
    """
    Poll Event Registry for new events and queue article fetching.

    Runs frequently (every few minutes). Skips events already in the
    database. Topic creation is deferred to fetch_event_articles so
    topics are only created when articles actually exist.
    """
    from .services import EventRegistryClient

    client = EventRegistryClient()

    try:
        events = client.fetch_recent_events()
    except Exception as e:
        logger.error(f"Error fetching events: {e}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))

    new_count = 0
    skipped_count = 0

    update_count = 0

    for event in events:
        event_uri = event.get("uri", "")
        if not event_uri:
            skipped_count += 1
            continue

        existing_topic = Topic.objects.filter(event_registry_uri=event_uri).first()
        if existing_topic:
            # Queue update for existing topic (will ingest any new articles)
            fetch_event_articles.delay(event_uri, existing_topic.id, False, event)
            update_count += 1
            continue

        # New event — queue article fetching (topic created on first articles)
        fetch_event_articles.delay(event_uri, None, False, event)
        new_count += 1

    logger.info(
        f"Fetched events: {new_count} new, {update_count} updates, "
        f"{skipped_count} skipped"
    )
    return f"{new_count} new, {update_count} updates, {skipped_count} skipped"


@shared_task(bind=True, max_retries=3)
def fetch_event_articles(self, event_uri, topic_id=None, sync=False, event_data=None):
    """
    Fetch articles for a specific event from Event Registry.

    Ingests articles from all English-language sources. Sources not yet
    in the database are auto-created.

    The topic is created lazily: if topic_id is None, the topic is only
    created after confirming Event Registry has articles for this event.

    Args:
        event_uri: The Event Registry event URI.
        topic_id: The local Topic ID to link articles to (None to auto-create).
        sync: If True, run analysis synchronously instead of queuing via Celery.
        event_data: Raw event dict from Event Registry (used to create topic).
    """
    from .services import EventRegistryClient

    # Resolve or defer topic creation
    topic = None
    if topic_id:
        try:
            topic = Topic.objects.get(id=topic_id)
        except Topic.DoesNotExist:
            logger.error(f"Topic {topic_id} not found")
            return

    # Cache known sources for fast lookup
    known_sources = {
        s.event_registry_uri: s
        for s in Source.objects.all()
    }

    client = EventRegistryClient()

    try:
        articles = client.fetch_event_articles(event_uri)
    except Exception as e:
        logger.error(f"Error fetching articles for event {event_uri}: {e}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))

    if not articles:
        logger.info(f"Event {event_uri}: no articles returned, skipping topic creation")
        return "0 articles, topic not created"

    # Create topic now that we know articles exist
    if topic is None:
        if event_data is None:
            logger.error(f"No topic_id and no event_data for event {event_uri}")
            return
        topic, created = _get_or_create_topic(event_data)
        if topic is None:
            logger.error(f"Could not create topic for event {event_uri}")
            return

    new_count = 0
    new_article_ids = []
    rank = 0

    for article_data in articles:
        article_url = article_data.get("url", "")
        if not article_url:
            continue

        # Find or create source
        source_data = article_data.get("source", {})
        source_uri = source_data.get("uri", "")
        if not source_uri:
            continue

        source = known_sources.get(source_uri)
        if not source:
            source_name = source_data.get("title", source_uri.split(".")[0].title())
            website_url = f"https://{source_uri}"
            source, created = Source.objects.get_or_create(
                event_registry_uri=source_uri,
                defaults={
                    'name': source_name[:200],
                    'website_url': website_url,
                }
            )
            known_sources[source_uri] = source
            if created:
                logger.info(f"Auto-created source: {source_name} ({source_uri})")

        # Extract article fields
        title = (article_data.get("title", "") or "")[:500]
        body = article_data.get("body", "") or ""
        sentiment = article_data.get("sentiment")
        er_article_uri = str(article_data.get("uri", ""))

        # Parse published datetime
        published_at = None
        date_time = article_data.get("dateTime") or article_data.get("dateTimePub")
        if date_time:
            try:
                from dateutil.parser import parse as parse_date
                published_at = parse_date(date_time)
                if timezone.is_naive(published_at):
                    published_at = timezone.make_aware(published_at)
            except (ValueError, TypeError):
                pass

        # Extract author
        authors = article_data.get("authors", [])
        author = ""
        if authors and isinstance(authors, list):
            author_names = [a.get("name", "") for a in authors if isinstance(a, dict)]
            author = ", ".join(n for n in author_names if n)[:300]

        image_url = (article_data.get("image", "") or "")[:2000]
        sim_score = article_data.get("sim", 0.0) or 0.0

        # Detect wire service republication
        from apps.articles.utils import is_wire_copy
        wire_flag = is_wire_copy(author, source_uri)

        from apps.analysis.tasks import analyze_article

        try:
            with transaction.atomic():
                article = Article.objects.create(
                    source=source,
                    title=title,
                    url=article_url,
                    author=author,
                    published_at=published_at,
                    content=body,
                    status=Article.ProcessingStatus.COMPLETE,
                    event_registry_uri=er_article_uri if er_article_uri else None,
                    sentiment=sentiment,
                    is_wire_content=wire_flag,
                    image_url=image_url,
                )

                ArticleCluster.objects.create(
                    topic=topic,
                    article=article,
                    confidence_score=sim_score,
                    cluster_rank=rank,
                )

                new_article_ids.append(article.id)

                # Queue analysis on commit so the worker sees the row
                if not sync:
                    article_id = article.id
                    transaction.on_commit(
                        lambda aid=article_id: analyze_article.delay(aid)
                    )
        except IntegrityError:
            # Article URL already exists (concurrent worker created it) — skip
            continue

        rank += 1
        new_count += 1

    # Sync-mode analysis: parallel via thread pool (single-process)
    if sync and new_article_ids:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        max_workers = min(len(new_article_ids), os.cpu_count() or 4)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(analyze_article, aid): aid for aid in new_article_ids}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"Analysis failed for article {futures[future]}: {e}")

    # Update topic metrics and image
    topic.update_metrics()
    # Re-attempt if image is missing OR is a stale external URL from a prior
    # failed download (some publishers' image hosts go down between fetches).
    if not topic.image_url or not topic.image_url.startswith('/static/'):
        candidates = (
            Article.objects.filter(cluster__topic=topic, image_url__gt='')
            .order_by('published_at')
            .values_list('image_url', flat=True)[:5]
        )
        for url in candidates:
            local_path = _download_topic_image(url, topic.slug)
            if local_path:
                topic.image_url = local_path
                topic.save(update_fields=['image_url'])
                break
        else:
            # All candidates failed — clear any stale URL so the card stays clean
            if topic.image_url and not topic.image_url.startswith('/static/'):
                topic.image_url = ''
                topic.save(update_fields=['image_url'])

    logger.info(f"Event {event_uri}: ingested {new_count} articles")
    return f"{new_count} articles ingested for event {event_uri}"


@shared_task
def cleanup_old_topics(days_old=30):
    """Remove topics older than N days with no recent articles."""
    cutoff = timezone.now() - timedelta(days=days_old)

    old_topics = Topic.objects.filter(
        last_article_at__lt=cutoff
    ) | Topic.objects.filter(
        last_article_at__isnull=True,
        created_at__lt=cutoff
    )

    count = old_topics.count()
    old_topics.delete()

    logger.info(f"Cleaned up {count} old topics")
    return f"Deleted {count} old topics"
