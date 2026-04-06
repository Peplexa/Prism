"""Management command to bulk import events from Event Registry."""

from django.core.management.base import BaseCommand

from apps.articles.services import EventRegistryClient
from apps.articles.tasks import fetch_event_articles
from apps.topics.models import Topic


class Command(BaseCommand):
    help = "Bulk import events from Event Registry to seed the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Number of days to look back (default: 7)",
        )
        parser.add_argument(
            "--max-events",
            type=int,
            default=200,
            help="Maximum number of events to import (default: 200)",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Fetch articles synchronously instead of queuing Celery tasks",
        )

    def handle(self, *args, **options):
        days = options["days"]
        max_events = options["max_events"]
        sync = options["sync"]
        hours = days * 24

        self.stdout.write(f"Fetching events from the last {days} days...")

        client = EventRegistryClient()
        events = client.fetch_recent_events(hours=hours, max_items=max_events)

        self.stdout.write(f"Found {len(events)} events from Event Registry")

        new_count = 0
        skipped_count = 0

        for event in events:
            event_uri = event.get("uri", "")
            if not event_uri:
                skipped_count += 1
                continue

            # Skip events we already have
            if Topic.objects.filter(event_registry_uri=event_uri).exists():
                skipped_count += 1
                continue

            title = event.get("title", {})
            title_str = title.get("eng", "") if isinstance(title, dict) else str(title)
            self.stdout.write(f"  Importing event: {title_str[:80]}")

            new_count += 1

            if sync:
                # Fetch articles immediately — topic created inside if articles exist
                result = fetch_event_articles(event_uri, None, sync=True, event_data=event)
                self.stdout.write(f"    -> {result}")
            else:
                fetch_event_articles.delay(event_uri, None, False, event)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone! {new_count} new events imported, {skipped_count} skipped."
            )
        )
