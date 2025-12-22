#!/usr/bin/env python
"""Seed initial news sources into the database."""

import os
import sys
import django

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
django.setup()

from apps.articles.models import Source


INITIAL_SOURCES = [
    {
        'name': 'NPR',
        'slug': 'npr',
        'website_url': 'https://www.npr.org',
        'discovery_method': Source.DiscoveryMethod.RSS,
        'discovery_url': 'https://feeds.npr.org/1001/rss.xml',
        'known_bias': Source.BiasRating.LEFT,
    },
    {
        'name': 'The Guardian',
        'slug': 'the-guardian',
        'website_url': 'https://www.theguardian.com',
        'discovery_method': Source.DiscoveryMethod.RSS,
        'discovery_url': 'https://www.theguardian.com/world/rss',
        'known_bias': Source.BiasRating.LEFT,
    },
    {
        'name': 'AP News',
        'slug': 'ap-news',
        'website_url': 'https://apnews.com',
        'discovery_method': Source.DiscoveryMethod.SITEMAP,
        'discovery_url': 'https://apnews.com/sitemap.xml',
        'known_bias': Source.BiasRating.CENTER,
    },
    {
        'name': 'Reuters',
        'slug': 'reuters',
        'website_url': 'https://www.reuters.com',
        'discovery_method': Source.DiscoveryMethod.SITEMAP,
        'discovery_url': 'https://www.reuters.com/sitemap_news_index.xml',
        'known_bias': Source.BiasRating.CENTER,
    },
    {
        'name': 'Fox News',
        'slug': 'fox-news',
        'website_url': 'https://www.foxnews.com',
        'discovery_method': Source.DiscoveryMethod.HOMEPAGE,
        'discovery_url': 'https://www.foxnews.com',
        'article_link_selector': 'article a[href*="/"], .story a[href*="/"]',
        'known_bias': Source.BiasRating.RIGHT,
    },
    {
        'name': 'Daily Wire',
        'slug': 'daily-wire',
        'website_url': 'https://www.dailywire.com',
        'discovery_method': Source.DiscoveryMethod.HOMEPAGE,
        'discovery_url': 'https://www.dailywire.com/news',
        'article_link_selector': 'a[href*="/news/"]',
        'known_bias': Source.BiasRating.RIGHT,
    },
]


def seed_sources():
    """Create or update initial news sources."""
    created = 0
    updated = 0

    for source_data in INITIAL_SOURCES:
        source, was_created = Source.objects.update_or_create(
            slug=source_data['slug'],
            defaults=source_data,
        )

        if was_created:
            created += 1
            print(f"Created: {source.name}")
        else:
            updated += 1
            print(f"Updated: {source.name}")

    print(f"\nDone! Created {created}, updated {updated} sources.")


if __name__ == '__main__':
    seed_sources()
