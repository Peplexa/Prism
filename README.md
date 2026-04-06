# Prism

A news aggregation and topic clustering platform that collects articles from multiple sources, groups them into topics using ML-based clustering, and tracks trending stories.

## Features

- **Multi-source aggregation** - Supports RSS feeds, sitemaps, and homepage scraping
- **Semantic clustering** - Groups related articles using sentence transformers and HDBSCAN
- **Trending detection** - Real-time trending scores based on recency and source diversity
- **Bias tracking** - Records political bias ratings for each news source, implemented as how other news sites do it currently. This is what needs to be changed next.
- **Live search** - HTMX-powered search without full page reloads
- **REST API** - Full API for building alternative frontends

## Tech Stack

- **Backend:** Django, Django REST Framework, Celery
- **Database:** PostgreSQL, Redis
- **ML/NLP:** Sentence Transformers, scikit-learn, HDBSCAN
- **Scraping:** Trafilatura, FeedParser, BeautifulSoup4
- **Frontend:** Django Templates, HTMX

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+

### Setup

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd Prism
   ```

2. Copy the environment file and configure:
   ```bash
   cp .env.example .env
   # Edit .env with your settings (especially SECRET_KEY for production)
   ```

3. Start the services:
   ```bash
   docker-compose up -d
   ```

4. Run migrations:
   ```bash
   docker-compose exec web python manage.py migrate
   ```

5. Access the application at `http://localhost:8000`

## Project Structure

```
Prism/
├── apps/
│   ├── articles/      # Article models, scrapers, and API
│   ├── topics/        # Topic clustering and trending
│   ├── core/          # Shared utilities
│   └── web/           # Frontend views
├── config/            # Django settings and Celery config
├── templates/         # HTML templates
├── static/            # CSS/JS assets
├── tests/             # Test suite
└── scripts/           # Utility scripts
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/v1/articles/` | List articles |
| `GET /api/v1/articles/sources/` | List news sources |
| `GET /api/v1/topics/` | List all topics |
| `GET /api/v1/topics/trending/` | Top 20 trending topics |
| `GET /api/v1/topics/<slug>/` | Topic details with articles |

## Background Tasks

Celery Beat runs these scheduled tasks:

| Schedule | Task | Description |
|----------|------|-------------|
| Every hour | `scrape_all_sources` | Discover new articles |
| Every 30 min | `cluster_recent_articles` | Group articles into topics |
| Every 15 min | `update_trending_scores` | Update popularity scores |
| Daily 3 AM | `cleanup_failed_articles` | Remove old failed articles |
| Daily 4 AM | `merge_similar_topics` | Consolidate duplicate topics |

## Running Tests

```bash
# Using the test script
./scripts/run_tests.sh    # Linux/Mac
scripts\run_tests.bat     # Windows

# Or directly with pytest
pytest --cov=apps
```

