from __future__ import annotations

from io import StringIO

from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase, override_settings

from core.models import ScraperIncident


class BootstrapScraperOpsCommandTestCase(TestCase):
    @override_settings(
        SCRAPER_INCIDENT_VIEWER_GROUPS=["ScraperViewers"],
        SCRAPER_INCIDENT_RESOLVER_GROUPS=["ScraperResolvers"],
    )
    def test_bootstrap_creates_groups(self):
        stdout = StringIO()

        call_command("bootstrap_scraper_ops", stdout=stdout)

        self.assertTrue(Group.objects.filter(name="ScraperViewers").exists())
        self.assertTrue(Group.objects.filter(name="ScraperResolvers").exists())
        self.assertIn("Scraper ops groups ready", stdout.getvalue())


class SimulateScraperContingencyCommandTestCase(TestCase):
    @override_settings(
        SCRAPER_TELEGRAM_BOT_TOKEN="telegram-token",
        SCRAPER_TELEGRAM_CHAT_IDS=["1001"],
    )
    def test_simulate_missing_group_creates_incident_in_dry_run_mode(self):
        stdout = StringIO()

        call_command(
            "simulate_scraper_contingency",
            scenario="missing_group",
            scraper="lotoven_triples",
            stdout=stdout,
        )

        incident = ScraperIncident.objects.get(scraper_key="lotoven_triples")
        self.assertEqual(incident.failure_reason_code, "missing_expected_group")
        self.assertIn("incident_created", stdout.getvalue())
