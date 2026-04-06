"""Tests for the seed_sources management command."""

import pytest
from django.core.management import call_command

from apps.articles.models import Source


@pytest.mark.django_db
class TestSeedSourcesCommand:
    def test_creates_sources(self):
        call_command("seed_sources")
        assert Source.objects.count() >= 12

    def test_all_sources_active(self):
        call_command("seed_sources")
        assert Source.objects.filter(is_active=False).count() == 0

    def test_idempotent(self):
        call_command("seed_sources")
        first_count = Source.objects.count()
        call_command("seed_sources")
        assert Source.objects.count() == first_count

    def test_clear_flag(self):
        call_command("seed_sources")
        assert Source.objects.count() >= 12
        call_command("seed_sources", clear=True)
        assert Source.objects.count() >= 12

    def test_bias_diversity(self):
        call_command("seed_sources")
        biases = set(Source.objects.values_list("known_bias", flat=True))
        # Should have at least: left, center_left, center, center_right, right
        assert len(biases) >= 4
        assert "center" in biases
        assert "right" in biases

    def test_event_registry_uris_unique(self):
        call_command("seed_sources")
        uris = list(Source.objects.values_list("event_registry_uri", flat=True))
        assert len(uris) == len(set(uris))
