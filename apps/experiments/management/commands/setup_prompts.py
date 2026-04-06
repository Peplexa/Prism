"""
Management command to set up initial prompt versions.
"""

from django.core.management.base import BaseCommand

from apps.experiments.models import PromptVersion
from apps.extraction.services.prompts import (
    BILLSUM_SYSTEM_PROMPT,
    BILLSUM_USER_TEMPLATE,
    ROTOWIRE_SYSTEM_PROMPT,
    ROTOWIRE_USER_TEMPLATE,
)


class Command(BaseCommand):
    help = "Set up initial prompt versions for extraction"

    def handle(self, *args, **options):
        prompts = [
            {
                "name": "rotowire_default",
                "version": "1.0",
                "system_prompt": ROTOWIRE_SYSTEM_PROMPT,
                "user_prompt_template": ROTOWIRE_USER_TEMPLATE,
                "description": "Default prompt for NBA game summary extraction",
                "is_active": True,
            },
            {
                "name": "billsum_default",
                "version": "1.0",
                "system_prompt": BILLSUM_SYSTEM_PROMPT,
                "user_prompt_template": BILLSUM_USER_TEMPLATE,
                "description": "Default prompt for legislative text extraction",
                "is_active": True,
            },
        ]

        created_count = 0
        for prompt_data in prompts:
            prompt, created = PromptVersion.objects.get_or_create(
                name=prompt_data["name"],
                version=prompt_data["version"],
                defaults={
                    "system_prompt": prompt_data["system_prompt"],
                    "user_prompt_template": prompt_data["user_prompt_template"],
                    "description": prompt_data["description"],
                    "is_active": prompt_data["is_active"],
                },
            )
            if created:
                created_count += 1
                self.stdout.write(f"Created: {prompt.name} v{prompt.version}")
            else:
                self.stdout.write(f"Exists: {prompt.name} v{prompt.version}")

        self.stdout.write(
            self.style.SUCCESS(f"Setup complete: {created_count} new prompts created")
        )
