"""
Quick test script for NewsAPI.ai integration.
Run: python scripts/test_newsapi.py
"""

import os
import sys

# Load .env
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from eventregistry import (
    EventRegistry,
    QueryArticlesIter,
    QueryItems,
    ReturnInfo,
    ArticleInfoFlags,
)


def test_article_search(api_key):
    """Search for recent articles on a topic from multiple sources."""
    er = EventRegistry(apiKey=api_key, allowUseOfArchive=False)

    print("=== Searching for recent articles ===\n")

    q = QueryArticlesIter(
        keywords="immigration policy",
        lang="eng",
    )

    count = 0
    sources_seen = set()
    for article in q.execQuery(
        er,
        sortBy="date",
        returnInfo=ReturnInfo(
            articleInfo=ArticleInfoFlags(
                body=True,
                sentiment=True,
                concepts=True,
            )
        ),
        maxItems=10,
    ):
        count += 1
        source = article.get("source", {}).get("title", "Unknown")
        sources_seen.add(source)
        title = article.get("title", "No title")
        sentiment = article.get("sentiment", "N/A")
        body_len = len(article.get("body", ""))
        date = article.get("dateTimePub", "Unknown date")

        print(f"{count}. [{source}] {title}")
        print(f"   Date: {date} | Sentiment: {sentiment} | Body: {body_len} chars")
        print()

    print(f"--- Found {count} articles from {len(sources_seen)} sources ---")
    print(f"Sources: {', '.join(sorted(sources_seen))}")


def test_event_search(api_key):
    """Search for events (clusters of articles about the same story)."""
    from eventregistry import QueryEvents, RequestEventsInfo, EventInfoFlags

    er = EventRegistry(apiKey=api_key, allowUseOfArchive=False)

    print("\n=== Searching for events (article clusters) ===\n")

    q = QueryEvents(keywords="immigration policy", lang="eng")
    q.setRequestedResult(
        RequestEventsInfo(
            count=5,
            sortBy="date",
            returnInfo=ReturnInfo(
                eventInfo=EventInfoFlags(
                    title=True,
                    summary=True,
                    articleCounts=True,
                    concepts=True,
                )
            ),
        )
    )

    res = er.execQuery(q)
    events = res.get("events", {}).get("results", [])

    for i, event in enumerate(events, 1):
        title = event.get("title", {}).get("eng", "No title")
        summary = event.get("summary", {}).get("eng", "")[:200]
        article_count = event.get("totalArticleCount", 0)
        date = event.get("eventDate", "Unknown")

        print(f"{i}. {title}")
        print(f"   Date: {date} | Articles: {article_count}")
        if summary:
            print(f"   Summary: {summary}...")
        print()

    print(f"--- Found {len(events)} events ---")


if __name__ == "__main__":
    api_key = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("NEWSAPI_AI_KEY", "")
    if not api_key:
        print("No API key found. Set NEWSAPI_AI_KEY in .env or pass as argument.")
        sys.exit(1)

    print(f"Using API key: {api_key[:8]}...{api_key[-4:]}\n")
    test_article_search(api_key)
    test_event_search(api_key)

    print("\nDone! Free tier gives you 2,000 tokens total.")
