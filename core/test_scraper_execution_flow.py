from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import CurrentResult, Provider, ScraperExecution, ScraperHealth, ScraperIncident
from core.services.scraper_execution_service import (
    BASELINE_PROVIDER_START_TIMES,
    LOTOVEN_ANIMALITO_BASELINE_PROVIDERS,
    LOTOVEN_STRICT_SCHEDULE,
    LOTOVEN_TABLE_SIMPLE_PROVIDERS,
    SCRAPER_SCOPE_START_TIMES,
    ScraperExecutionService,
    STRICT_EXPECTED_GROUP_GRACE_MINUTES,
)
from core.services.scraper_health_service import ScraperHealthService
from core.services.scraper_notification_service import ScraperNotificationService


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
        self.assertFalse(incident.alert_sent)
        mock_post.assert_not_called()

        monitor = ScraperHealth.objects.get(scraper_key="lotoven_triples")
        self.assertEqual(monitor.last_status, ScraperHealth.Status.FAILED)
        self.assertIn("Triple Caracas A 16:30", monitor.last_error_message)
        self.assertIsNone(monitor.last_notified_at)

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
        self.assertEqual(mock_post.call_count, 0)

        monitor = ScraperHealth.objects.get(scraper_key="lotoven_triples")
        self.assertEqual(monitor.last_status, ScraperHealth.Status.SUCCESS)

    def test_missing_groups_accepts_nearby_persisted_time_within_tolerance(self):
        expected_groups = [
            {"provider_name": "Triple Caracas A", "draw_time": "16:30", "scope": "group"},
        ]
        persisted_groups = [
            {"provider_name": "Triple Caracas A", "draw_time": "16:40", "scope": "group"},
        ]

        missing = ScraperExecutionService._get_missing_groups(expected_groups, persisted_groups)

        self.assertEqual(missing, [])

    def test_due_expected_groups_waits_for_grace_window(self):
        now = timezone.make_aware(
            datetime(2026, 3, 23, 16, 30 + STRICT_EXPECTED_GROUP_GRACE_MINUTES - 1, 0),
            timezone.get_current_timezone(),
        )

        groups = ScraperExecutionService._get_due_expected_groups(
            "lotoven_triples",
            self.draw_date,
            now=now,
        )

        self.assertNotIn(
            {"provider_name": "Triple Caracas A", "draw_time": "16:30", "scope": "group"},
            groups,
        )

    def test_due_expected_groups_waits_for_lotoven_baseline_start(self):
        start_time = BASELINE_PROVIDER_START_TIMES["lotoven_triples"]
        start_hour, start_minute = [int(value) for value in start_time.split(":")]
        now = timezone.make_aware(
            datetime(2026, 3, 23, start_hour, start_minute - 1, 0),
            timezone.get_current_timezone(),
        )

        groups = ScraperExecutionService._get_due_expected_groups(
            "lotoven_triples",
            self.draw_date,
            now=now,
        )

        self.assertNotIn(
            {"provider_name": "Triple Centena", "draw_time": "", "scope": "provider"},
            groups,
        )

    def test_due_expected_groups_waits_for_tuazar_baseline_start(self):
        start_time = BASELINE_PROVIDER_START_TIMES["tuazar_triples"]
        start_hour, start_minute = [int(value) for value in start_time.split(":")]
        now = timezone.make_aware(
            datetime(2026, 3, 23, start_hour, start_minute - 1, 0),
            timezone.get_current_timezone(),
        )

        groups = ScraperExecutionService._get_due_expected_groups(
            "tuazar_triples",
            self.draw_date,
            now=now,
        )

        self.assertEqual(groups, [])

    def test_due_expected_groups_waits_for_lotoven_animalitos_scraper_start(self):
        start_time = SCRAPER_SCOPE_START_TIMES["lotoven_animalitos"]
        start_hour, start_minute = [int(value) for value in start_time.split(":")]
        now = timezone.make_aware(
            datetime(2026, 3, 23, start_hour, start_minute - 1, 0),
            timezone.get_current_timezone(),
        )

        groups = ScraperExecutionService._get_due_expected_groups(
            "lotoven_animalitos",
            self.draw_date,
            now=now,
        )

        self.assertEqual(groups, [])

    def test_due_expected_groups_includes_lotoven_animalito_baseline_providers_after_start(self):
        start_time = SCRAPER_SCOPE_START_TIMES["lotoven_animalitos"]
        start_hour, start_minute = [int(value) for value in start_time.split(":")]
        now = timezone.make_aware(
            datetime(2026, 3, 23, start_hour, start_minute + 1, 0),
            timezone.get_current_timezone(),
        )

        groups = ScraperExecutionService._get_due_expected_groups(
            "lotoven_animalitos",
            self.draw_date,
            now=now,
        )

        self.assertIn(
            {"provider_name": "Lotto Rey", "draw_time": "", "scope": "provider"},
            groups,
        )
        self.assertIn(
            {"provider_name": "Mega Animal 40", "draw_time": "", "scope": "provider"},
            groups,
        )
        self.assertEqual(
            len([group for group in groups if group["scope"] == "provider"]),
            len(LOTOVEN_ANIMALITO_BASELINE_PROVIDERS),
        )

    @override_settings(
        SCRAPER_TELEGRAM_BOT_TOKEN="telegram-token",
        SCRAPER_TELEGRAM_CHAT_IDS=["1001"],
    )
    @patch("core.services.scraper_notification_service.requests.post")
    def test_notify_pending_incidents_waits_for_persistent_missing_group(self, mock_post):
        incident = ScraperIncident.objects.create(
            fingerprint="lotoven_triples|2026-03-23|group|Triple Caracas A|16:30|missing_expected_group",
            scraper_key="lotoven_triples",
            label="Triples Lotoven",
            command_name="scrape_lotoven_tables",
            draw_date=self.draw_date,
            provider_name="Triple Caracas A",
            draw_time=datetime.strptime("16:30", "%H:%M").time(),
            result_model="CurrentResult",
            detection_scope="group",
            validation_profile="strict_schedule",
            status=ScraperIncident.Status.OPEN,
            failure_reason_code="missing_expected_group",
            summary="Falta el grupo esperado.",
            evidence_summary="test",
            occurrence_count=2,
            first_detected_at=self.fixed_now - timedelta(minutes=10),
            last_detected_at=self.fixed_now,
        )

        sent = ScraperNotificationService.notify_pending_incidents(
            incidents=[incident],
            now=self.fixed_now,
        )

        self.assertEqual(sent, 0)
        incident.refresh_from_db()
        self.assertFalse(incident.alert_sent)
        mock_post.assert_not_called()

        incident.occurrence_count = 3
        incident.first_detected_at = self.fixed_now - timedelta(minutes=25)
        incident.save(update_fields=["occurrence_count", "first_detected_at", "updated_at"])

        sent = ScraperNotificationService.notify_pending_incidents(
            incidents=[incident],
            now=self.fixed_now,
        )

        self.assertEqual(sent, 1)
        incident.refresh_from_db()
        self.assertTrue(incident.alert_sent)
        self.assertIsNotNone(incident.alert_sent_at)
        mock_post.assert_called_once()

    @patch("core.services.scraper_notification_service.requests.post")
    @patch("core.services.scraper_health_service.call_command")
    def test_successful_rerun_retires_obsolete_open_contract_incident(self, mock_call_command, mock_post):
        obsolete_incident = ScraperIncident.objects.create(
            fingerprint="lotoven_triples|2026-03-22|group|Triple Caracas A|19:10|missing_expected_group",
            scraper_key="lotoven_triples",
            label="Triples Lotoven",
            command_name="scrape_lotoven_tables",
            draw_date=self.draw_date,
            provider_name="Triple Caracas A",
            draw_time=datetime.strptime("19:10", "%H:%M").time(),
            result_model="CurrentResult",
            detection_scope="group",
            validation_profile="strict_schedule",
            status=ScraperIncident.Status.OPEN,
            failure_reason_code="missing_expected_group",
            summary="Horario viejo aun abierto.",
            evidence_summary="test",
        )

        def create_full_rows(_command_name):
            self._seed_lotoven_results()
            return None

        mock_call_command.side_effect = create_full_rows

        with patch("core.services.scraper_health_service.timezone.now", return_value=self.fixed_now):
            with patch("core.services.scraper_execution_service.timezone.now", return_value=self.fixed_now):
                with patch(
                    "core.services.scraper_execution_service.timezone.localdate",
                    return_value=self.draw_date,
                ):
                    ScraperHealthService.run_registered("lotoven_triples")

        obsolete_incident.refresh_from_db()
        self.assertEqual(obsolete_incident.status, ScraperIncident.Status.RESOLVED)
        self.assertIn("contrato operativo", obsolete_incident.resolution_note)
        mock_post.assert_not_called()

    def test_lotoven_animalitos_without_rows_keeps_single_scraper_incident(self):
        expected_groups = [
            {"provider_name": "Lotto Rey", "draw_time": "", "scope": "provider"},
            {"provider_name": "Mega Animal 40", "draw_time": "", "scope": "provider"},
        ]

        candidates = ScraperExecutionService._build_incident_candidates(
            scraper_key="lotoven_animalitos",
            draw_date=self.draw_date,
            expected_groups=expected_groups,
            persisted_groups=[],
            missing_groups=expected_groups,
            now=self.fixed_now,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].failure_reason_code, "missing_scraper_rows")

    def test_lotoven_animalitos_partial_rows_open_missing_provider_incidents(self):
        expected_groups = [
            {"provider_name": "Lotto Rey", "draw_time": "", "scope": "provider"},
            {"provider_name": "Mega Animal 40", "draw_time": "", "scope": "provider"},
        ]
        persisted_groups = [
            {"provider_name": "Lotto Rey", "draw_time": "", "scope": "provider"},
            {"provider_name": "", "draw_time": "", "scope": "scraper"},
        ]
        missing_groups = [
            {"provider_name": "Mega Animal 40", "draw_time": "", "scope": "provider"},
        ]

        candidates = ScraperExecutionService._build_incident_candidates(
            scraper_key="lotoven_animalitos",
            draw_date=self.draw_date,
            expected_groups=expected_groups,
            persisted_groups=persisted_groups,
            missing_groups=missing_groups,
            now=self.fixed_now,
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].failure_reason_code, "missing_provider_rows")
        self.assertEqual(candidates[0].provider_name, "Mega Animal 40")
