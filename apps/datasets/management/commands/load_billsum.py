"""
Management command to load BillSum dataset.
"""

from django.core.management.base import BaseCommand
from tqdm import tqdm

from apps.datasets.loaders import BillSumLoader
from apps.datasets.models import DataSource, Document, GroundTruthFact


class Command(BaseCommand):
    help = "Load BillSum dataset into database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--split",
            default="train",
            choices=["train", "test", "ca_test"],
            help="Data split to load",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of documents to load",
        )
        parser.add_argument(
            "--extract-facts",
            action="store_true",
            help="Extract ground truth facts from summaries",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing data for this source before loading",
        )

    def handle(self, *args, **options):
        split = options["split"]
        limit = options["limit"]
        extract_facts = options["extract_facts"]
        clear = options["clear"]

        loader = BillSumLoader()

        # Get or create data source
        source, created = DataSource.objects.get_or_create(
            name=loader.name,
            defaults={
                "description": loader.description,
                "loader_class": "apps.datasets.loaders.BillSumLoader",
            },
        )

        if created:
            self.stdout.write(f"Created data source: {source.name}")

        if clear:
            deleted, _ = Document.objects.filter(source=source, split=split).delete()
            self.stdout.write(f"Cleared {deleted} existing documents for {split} split")

        # Load documents
        self.stdout.write(f"Loading BillSum {split} split (this may download data)...")

        docs_created = 0
        docs_skipped = 0
        facts_created = 0

        for doc_data in tqdm(loader.load(split=split, limit=limit), desc="Loading documents"):
            # Create or get document
            doc, created = Document.objects.get_or_create(
                source=source,
                external_id=doc_data["external_id"],
                defaults={
                    "split": split,
                    "primary_text": doc_data["primary_text"],
                    "reference_content": doc_data["reference_content"],
                    "title": doc_data["title"],
                    "metadata": doc_data["metadata"],
                },
            )

            if created:
                docs_created += 1

                if extract_facts:
                    # Extract ground truth facts from summary
                    facts = loader.extract_ground_truth(doc_data)
                    for fact_data in facts:
                        GroundTruthFact.objects.create(
                            document=doc,
                            fact_text=fact_data["fact_text"],
                            fact_type=fact_data["fact_type"],
                            confidence=fact_data["confidence"],
                            metadata=fact_data["metadata"],
                        )
                        facts_created += 1
            else:
                docs_skipped += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Loaded {docs_created} documents, skipped {docs_skipped} existing"
            )
        )
        if extract_facts:
            self.stdout.write(
                self.style.SUCCESS(f"Created {facts_created} ground truth facts")
            )
