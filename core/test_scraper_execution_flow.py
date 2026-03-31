from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.models import CurrentResult, Provider, ScraperExecution, ScraperHealth, ScraperIncident
from core.services.scraper_execution_service import (
    LOTOVEN_STRICT_SCHEDULE,
    LOTOVEN_TABLE_SIMPLE_PROVIDERS,
    ScraperExecutionService,
    STRICT_EXPECTED_GROUP_GRACE_MINUTES,
)
from core.services.scraper_health_service import ScraperHealthService


class ScraperExecutionFlowTestCase(TestCase):
    def setUp(self):
        naive_dt = datetime(2026, 3, 23, 20, 0, 0)
        self.fixed_now = timezone.make_aware(naive_dt, timezone.get_current_timezone())
        self.draw_date = self.fixed_now.date()

    def _upsert_provider(self, name: str) -> Provider:
        provider, _ = Provider.objects.get_or_create(
            name=name,
            defaults={"source_url": "https://lotoven.com", "is_active": True, "logo_url": ""},
        )
        return provider

    def _seed_lotoven_results(self, *, missing_group: tuple[str, str] | None = None) -> None:
        for provider_name in LOTOVEN_TABLE_SIMPLE_PROVIDERS:
            provider = self._upsert_provider(provider_name)
            CurrentResult.objects.update_or_create(
                provider=provider,
                draw_date=self.draw_date,
                draw_time=datetime.strptime("08:00", "%H:%M").time(),
                defaults={"winning_number": "111", "image_url": "", "extra": None},
            )

        for provider_name, times in LOTOVEN_STRICT_SCHEDULE.items():
            provider = self._upsert_provider(provider_name)
            for time_str in times:
                if missing_group == (provider_name, time_str):
                    continue
                CurrentResult.objects.update_or_create(
                    provider=provider,
                    draw_date=self.draw_date,
                    draw_time=datetime.strptime(time_str, "%H:%M").time(),
                    defaults={"winning_number": "222", "image_url": "", "extra": None},
                )

    @patch("core.services.scraper_notification_service.requests.post")
    @patch("core.services.scraper_health_service.call_command")
    def test_run_registered_failure_creates_failed_execution_and_incident(self, mock_call_command, mock_post):
        mock_call_command.side_effect = RuntimeError("condor parser failed")

        with patch("core.services.scraper_health_service.timezone.now", return_value=self.fixed_now):
            with patch("core.services.scraper_execution_service.timezone.now", return_value=self.fixed_now):
                with patch(
                    "core.services.scraper_execution_service.timezone.localdate",
                    return_value=self.draw_date,
                ):
                    with patch("django.conf.settings.SCRAPER_TELEGRAM_BOT_TOKEN", "telegram-token"):
                        with patch("django.conf.settings.SCRAPER_TELEGRAM_CHAT_IDS", ["1001"]):
                            with self.assertRaises(RuntimeError):
                                ScraperHealthService.run_registered("condor_animalitos")

        execution = ScraperExecution.objects.get(scraper_key="condor_animalitos")
        self.assertEqual(execution.status, ScraperExecution.Status.FAILED)
        self.assertTrue(execution.incident_detected)
        self.assertEqual(execution.failure_reason_code, "command_failed")

        incident = ScraperIncident.objects.get(scraper_key="condor_animalitos")
        self.assertEqual(incident.status, ScraperIncident.Status.OPEN)
        self.assertEqual(incident.failure_reason_code, "command_failed")
        self.assertTrue(incident.alert_sent)
        self.assertIsNotNone(incident.alert_sent_at)
        mock_post.assert_called_once()

        monitor = ScraperHealth.objects.get(scraper_key="condor_animalitos")
        self.assertEqual(monitor.last_status, ScraperHealth.Status.FAILED)
        self.assertIn("condor parser failed", monitor.last_error_message)
        self.assertIsNotNone(monitor.last_notified_at)

    @patch("core.services.scraper_notification_service.requests.post")
    @patch("core.services.scraper_health_service.call_command")
    def test_run_registered_detects_missing_strict_group_as_incident(self, mock_call_command, mock_post):
        def create_partial_lotoven(_command_name):
            self._seed_lotoven_results(missing_group=("Triple Caracas A", "16:30"))
            return None

        mock_call_command.side_effect = create_partial_lotoven

        with patch("core.services.scraper_health_service.timezone.now", return_value=self.fixed_now):
            with patch("core.services.scraper_execution_service.timezone.now", return_value=self.fixed_now):
                with patch(
                    "core.services.scraper_execution_service.timezone.localdate",
                    return_value=self.draw_date,
                ):
                    with patch("django.conf.settings.SCRAPER_TELEGRAM_BOT_TOKEN", "telegram-token"):
                        with patch("django.conf.settings.SCRAPER_TELEGRAM_CHAT_IDS", ["1001"]):
                            ScraperHealthService.run_registered("lotoven_triples")

        execution = ScraperExecution.objects.filter(scraper_key="lotoven_triples").latest("id")
        self.assertEqual(execution.status, ScraperExecution.Status.INCIDENT)
        self.assertTrue(execution.incident_detected)
        self.assertIn(
            {"provider_name": "Triple Caracas A", "draw_time": "16:30", "scope": "group"},
            execution.missing_groups,
        )

        incident = ScraperIncident.objects.get(
            scraper_key="lotoven_triples",
            provider_name="Triple Caracas A",
            failure_reason_code="missing_expected_group",
        )
        self.assertEqual(incident.status, ScraperIncident.Status.OPEN)
        self.assertEqual(incident.draw_time.strftime("%H:%M"), "16:30")
        self.assertTrue(incident.alert_sent)
        mock_post.assert_called_once()

        monitor = ScraperHealth.objects.get(scraper_key="lotoven_triples")
        self.assertEqual(monitor.last_status, ScraperHealth.Status.FAILED)
        self.assertIn("Triple Caracas A 16:30", monitor.last_error_message)
        self.assertIsNotNone(monitor.last_notified_at)

    @patch("core.services.scraper_notification_service.requests.post")
    @patch("core.services.scraper_health_service.call_command")
    def test_successful_rerun_resolves_open_missing_group_incident(self, mock_call_command, mock_post):
        run_number = {"value": 0}

        def create_rows(_command_name):
            run_number["value"] += 1
            if run_number["value"] == 1:
                self._seed_lotoven_results(missing_group=("Triple Caracas A", "16:30"))
            else:
                self._seed_lotoven_results()
            return None

        mock_call_command.side_effect = create_rows

        with patch("core.services.scraper_health_service.timezone.now", return_value=self.fixed_now):
            with patch("core.services.scraper_execution_service.timezone.now", return_value=self.fixed_now):
                with patch(
                    "core.services.scraper_execution_service.timezone.localdate",
                    return_value=self.draw_date,
                ):
                    with patch("django.conf.settings.SCRAPER_TELEGRAM_BOT_TOKEN", "telegram-token"):
                        with patch("django.conf.settings.SCRAPER_TELEGRAM_CHAT_IDS", ["1001"]):
                            ScraperHealthService.run_registered("lotoven_triples")
                            ScraperHealthService.run_registered("lotoven_triples")

        latest_execution = ScraperExecution.objects.filter(scraper_key="lotoven_triples").latest("id")
        self.assertEqual(latest_execution.status, ScraperExecution.Status.SUCCESS)
        self.assertFalse(latest_execution.incident_detected)

        incident = ScraperIncident.objects.get(
            scraper_key="lotoven_triples",
            provider_name="Triple Caracas A",
            failure_reason_code="missing_expected_group",
        )
        self.assertEqual(incident.status, ScraperIncident.Status.RESOLVED)
        self.assertIsNotNone(incident.resolved_at)
        self.assertEqual(mock_post.call_count, 1)

        monitor = ScraperHealth.objects.get(scraper_key="lotoven_triples")
        self.assertEqual(monitor.last_status, ScraperHealth.Status.SUCCESS)

    def test_missing_groups_accepts_nearby_persisted_time_within_tolerance(self):
        expected_groups = [
            {"provider_name": "Triple Caracas A", "draw_time": "19:10", "scope": "group"},
        ]
        persisted_groups = [
            {"provider_name": "Triple Caracas A", "draw_time": "19:00", "scope": "group"},
        ]

        missing = ScraperExecutionService._get_missing_groups(expected_groups, persisted_groups)

        self.assertEqual(missing, [])

    def test_due_expected_groups_waits_for_grace_window(self):
        now = timezone.make_aware(
            datetime(2026, 3, 23, 19, 10 + STRICT_EXPECTED_GROUP_GRACE_MINUTES - 1, 0),
            timezone.get_current_timezone(),
        )

        groups = ScraperExecutionService._get_due_expected_groups(
            "lotoven_triples",
            self.draw_date,
            now=now,
        )

        self.assertNotIn(
            {"provider_name": "Triple Caracas A", "draw_time": "19:10", "scope": "group"},
            groups,
        )
