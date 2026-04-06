"""
Management command to extract nuggets from documents using LLM.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone
from tqdm import tqdm

from apps.datasets.models import DataSource, Document
from apps.experiments.models import PromptVersion
from apps.extraction.models import ExtractedNugget, ExtractionRun
from apps.extraction.services import NuggetExtractor
from apps.extraction.services.llm_client import get_llm_client


class Command(BaseCommand):
    help = "Extract nuggets from documents using local LLM"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            required=True,
            help="DataSource name (rotowire or billsum)",
        )
        parser.add_argument(
            "--split",
            default="test",
            help="Document split to process",
        )
        parser.add_argument(
            "--prompt-version",
            type=int,
            default=None,
            help="PromptVersion ID to use (optional, uses defaults if not specified)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of documents to process",
        )
        parser.add_argument(
            "--model",
            default=None,
            help="Override model name",
        )
        parser.add_argument(
            "--backend",
            default=None,
            choices=["ollama", "deepseek"],
            help="LLM backend: 'ollama' (local) or 'deepseek' (cloud API)",
        )
        parser.add_argument(
            "--name",
            default=None,
            help="Name for this extraction run",
        )

    def handle(self, *args, **options):
        source_name = options["source"]
        split = options["split"]
        prompt_version_id = options["prompt_version"]
        limit = options["limit"]
        model = options["model"]
        backend = options["backend"]
        run_name = options["name"]

        # Get data source
        try:
            source = DataSource.objects.get(name=source_name)
        except DataSource.DoesNotExist:
            self.stderr.write(
                self.style.ERROR(f"Data source '{source_name}' not found")
            )
            return

        # Get prompt version if specified
        prompt_version = None
        if prompt_version_id:
            try:
                prompt_version = PromptVersion.objects.get(pk=prompt_version_id)
            except PromptVersion.DoesNotExist:
                self.stderr.write(
                    self.style.ERROR(f"PromptVersion {prompt_version_id} not found")
                )
                return

        # Get documents
        documents = Document.objects.filter(source=source, split=split)
        if limit:
            documents = documents[:limit]

        total_docs = documents.count()
        if total_docs == 0:
            self.stderr.write(
                self.style.ERROR(
                    f"No documents found for {source_name} {split} split. "
                    f"Run load_{source_name} first."
                )
            )
            return

        # Get LLM client
        try:
            client = get_llm_client(backend)
            # Override model if specified
            if model:
                client.model = model
        except ValueError as e:
            self.stderr.write(self.style.ERROR(str(e)))
            return

        if not client.is_available():
            backend_name = backend or "default"
            self.stderr.write(
                self.style.ERROR(
                    f"LLM backend '{backend_name}' not available. "
                    f"Model: {client.model}"
                )
            )
            return

        self.stdout.write(f"Using backend: {backend or 'ollama'}, model: {client.model}")

        # Create extraction run
        if not run_name:
            run_name = f"{source_name}_{split}_{timezone.now().strftime('%Y%m%d_%H%M%S')}"

        extraction_run = ExtractionRun.objects.create(
            name=run_name,
            source=source,
            prompt_version=prompt_version,
            model_name=client.model,
            parameters={"temperature": 0.1},
            status="running",
            documents_total=total_docs,
            started_at=timezone.now(),
        )

        self.stdout.write(f"Created extraction run: {extraction_run.name} (ID: {extraction_run.pk})")
        self.stdout.write(f"Processing {total_docs} documents...")

        # Extract nuggets
        extractor = NuggetExtractor(client=client)
        nuggets_created = 0
        errors = 0

        for doc in tqdm(documents, desc="Extracting nuggets"):
            try:
                nuggets = extractor.extract(
                    doc.primary_text,
                    prompt_version=prompt_version,
                    domain=source_name,
                )

                for nugget in nuggets:
                    ExtractedNugget.objects.create(
                        extraction_run=extraction_run,
                        document=doc,
                        nugget_text=nugget["fact"],
                        nugget_type=nugget.get("type", ""),
                    )
                    nuggets_created += 1

                extraction_run.documents_processed += 1
                extraction_run.save(update_fields=["documents_processed"])

            except Exception as e:
                self.stderr.write(f"Error processing {doc.external_id}: {e}")
                errors += 1

        # Finalize run
        extraction_run.status = "completed" if errors == 0 else "completed"
        extraction_run.completed_at = timezone.now()
        if errors > 0:
            extraction_run.error_message = f"{errors} documents had errors"
        extraction_run.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Extraction complete: {nuggets_created} nuggets from "
                f"{extraction_run.documents_processed} documents"
            )
        )
        if errors > 0:
            self.stdout.write(self.style.WARNING(f"{errors} documents had errors"))

        self.stdout.write(f"Run ID: {extraction_run.pk}")
