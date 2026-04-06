"""Management command to seed tracked news sources."""

from django.core.management.base import BaseCommand

from apps.articles.models import Source


SOURCES = [
    # Left-leaning
    {
        "name": "CNN",
        "slug": "cnn",
        "website_url": "https://www.cnn.com",
        "event_registry_uri": "cnn.com",
        "known_bias": "left",
    },
    {
        "name": "NPR",
        "slug": "npr",
        "website_url": "https://www.npr.org",
        "event_registry_uri": "npr.org",
        "known_bias": "center_left",
    },
    {
        "name": "The New York Times",
        "slug": "new-york-times",
        "website_url": "https://www.nytimes.com",
        "event_registry_uri": "nytimes.com",
        "known_bias": "center_left",
    },
    {
        "name": "The Washington Post",
        "slug": "washington-post",
        "website_url": "https://www.washingtonpost.com",
        "event_registry_uri": "washingtonpost.com",
        "known_bias": "center_left",
    },
    # Center
    {
        "name": "Reuters",
        "slug": "reuters",
        "website_url": "https://www.reuters.com",
        "event_registry_uri": "reuters.com",
        "known_bias": "center",
    },
    {
        "name": "AP News",
        "slug": "ap-news",
        "website_url": "https://apnews.com",
        "event_registry_uri": "apnews.com",
        "known_bias": "center",
    },
    {
        "name": "BBC News",
        "slug": "bbc-news",
        "website_url": "https://www.bbc.com/news",
        "event_registry_uri": "bbc.co.uk",
        "known_bias": "center",
    },
    {
        "name": "USA Today",
        "slug": "usa-today",
        "website_url": "https://www.usatoday.com",
        "event_registry_uri": "usatoday.com",
        "known_bias": "center",
    },
    # Right-leaning
    {
        "name": "The Hill",
        "slug": "the-hill",
        "website_url": "https://thehill.com",
        "event_registry_uri": "thehill.com",
        "known_bias": "center_right",
    },
    {
        "name": "The Wall Street Journal",
        "slug": "wall-street-journal",
        "website_url": "https://www.wsj.com",
        "event_registry_uri": "wsj.com",
        "known_bias": "center_right",
    },
    {
        "name": "Fox News",
        "slug": "fox-news",
        "website_url": "https://www.foxnews.com",
        "event_registry_uri": "foxnews.com",
        "known_bias": "right",
    },
    {
        "name": "New York Post",
        "slug": "new-york-post",
        "website_url": "https://nypost.com",
        "event_registry_uri": "nypost.com",
        "known_bias": "right",
    },
]


class Command(BaseCommand):
    help = "Seed tracked news sources into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete all existing sources before seeding",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            count, _ = Source.objects.all().delete()
            self.stdout.write(f"Deleted {count} existing source records")

        created = 0
        updated = 0

        for data in SOURCES:
            _, was_created = Source.objects.update_or_create(
                slug=data["slug"],
                defaults={
                    "name": data["name"],
                    "website_url": data["website_url"],
                    "event_registry_uri": data["event_registry_uri"],
                    "known_bias": data["known_bias"],
                    "is_active": True,
                },
            )
            if was_created:
                created += 1
                self.stdout.write(f"  + {data['name']} ({data['known_bias']})")
            else:
                updated += 1
                self.stdout.write(f"  ~ {data['name']} (updated)")

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone: {created} created, {updated} updated. "
                f"Total active: {Source.objects.filter(is_active=True).count()}"
            )
        )
