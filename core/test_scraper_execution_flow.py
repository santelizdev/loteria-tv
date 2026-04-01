from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import AnimalitoResult, CurrentResult, Provider, ScraperExecution, ScraperHealth, ScraperIncident
from core.services.scraper_execution_service import (
    ANIMALITO_PROVIDER_SCHEDULE,
    CONDOR_PROVIDER_SCHEDULE,
    EXPECTED_GROUP_GRACE_MINUTES,
    FALLBACK_ATTEMPT_THRESHOLD,
    PRIMARY_ATTEMPT_THRESHOLD,
    ScraperExecutionService,
    TRIPLE_PROVIDER_SCHEDULE,
)
from core.services.scraper_health_service import ScraperHealthService
from core.services.scraper_notification_service import ScraperNotificationService
from core.services.tuazar_animalito_fallback_service import FallbackAttemptResult, TuAzarAnimalitoFallbackService


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
        for provider_name, times in TRIPLE_PROVIDER_SCHEDULE.items():
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

    def _seed_lotoven_animalitos_results(self, *, missing_provider: str | None = None) -> None:
        for provider_name, draw_times in ANIMALITO_PROVIDER_SCHEDULE.items():
            if provider_name == missing_provider:
                continue
            provider = self._upsert_provider(provider_name)
            provider.source_url = "https://lotoven.com/animalitos/"
            provider.logo_url = "https://lotoven.com/logo.png"
            provider.save(update_fields=["source_url", "logo_url"])
            for draw_time in draw_times:
                AnimalitoResult.objects.update_or_create(
                    provider=provider,
                    draw_date=self.draw_date,
                    draw_time=datetime.strptime(draw_time, "%H:%M").time(),
                    defaults={
                        "animal_number": "07",
                        "animal_name": "Perico",
                        "animal_image_url": "https://lotoven.com/animal.png",
                        "provider_logo_url": "https://lotoven.com/logo.png",
                    },
                )

    def _seed_condor_results(self, *, missing_time: str | None = None) -> None:
        provider = self._upsert_provider("Condor Gana")
        provider.source_url = "https://www.lottoresultados.com/resultados/animalitos/condor-gana"
        provider.save(update_fields=["source_url"])
        for draw_time in CONDOR_PROVIDER_SCHEDULE["Condor Gana"]:
            if draw_time == missing_time:
                continue
            AnimalitoResult.objects.update_or_create(
                provider=provider,
                draw_date=self.draw_date,
                draw_time=datetime.strptime(draw_time, "%H:%M").time(),
                defaults={
                    "animal_number": "09",
                    "animal_name": "Toro",
                    "animal_image_url": "https://condor.example/img.png",
                    "provider_logo_url": "",
                },
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
        self.assertEqual(monitor.last_status, ScraperHealth.Status.SUCCESS)
        self.assertEqual(monitor.last_error_message, "")
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
            datetime(2026, 3, 23, 16, 30 + EXPECTED_GROUP_GRACE_MINUTES - 1, 0),
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

    def test_due_expected_groups_waits_for_lotoven_first_due_slot(self):
        now = timezone.make_aware(
            datetime(2026, 3, 23, 8, EXPECTED_GROUP_GRACE_MINUTES - 1, 0),
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

    def test_due_expected_groups_waits_for_tuazar_first_due_slot(self):
        now = timezone.make_aware(
            datetime(2026, 3, 23, 8, EXPECTED_GROUP_GRACE_MINUTES - 1, 0),
            timezone.get_current_timezone(),
        )

        groups = ScraperExecutionService._get_due_expected_groups(
            "tuazar_triples",
            self.draw_date,
            now=now,
        )

        self.assertEqual(groups, [])

    def test_due_expected_groups_waits_for_lotoven_animalitos_first_due_slot(self):
        now = timezone.make_aware(
            datetime(2026, 3, 23, 8, EXPECTED_GROUP_GRACE_MINUTES - 1, 0),
            timezone.get_current_timezone(),
        )

        groups = ScraperExecutionService._get_due_expected_groups(
            "lotoven_animalitos",
            self.draw_date,
            now=now,
        )

        self.assertEqual(groups, [])

    def test_due_expected_groups_includes_lotoven_animalito_due_groups_after_grace(self):
        now = timezone.make_aware(
            datetime(2026, 3, 23, 9, EXPECTED_GROUP_GRACE_MINUTES + 1, 0),
            timezone.get_current_timezone(),
        )

        groups = ScraperExecutionService._get_due_expected_groups(
            "lotoven_animalitos",
            self.draw_date,
            now=now,
        )

        self.assertIn(
            {"provider_name": "Guacharo", "draw_time": "08:00", "scope": "group"},
            groups,
        )
        self.assertIn(
            {"provider_name": "Guacharito", "draw_time": "08:30", "scope": "group"},
            groups,
        )
        self.assertTrue(any(group["provider_name"] == "Lotto Rey" for group in groups))

    @override_settings(
        SCRAPER_TELEGRAM_BOT_TOKEN="telegram-token",
        SCRAPER_TELEGRAM_CHAT_IDS=["1001"],
    )
    @patch("core.services.scraper_notification_service.requests.post")
    def test_notify_pending_incidents_sends_group_manual_required(self, mock_post):
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
            contingency_stage=ScraperIncident.ContingencyStage.OBSERVING,
            occurrence_count=3,
            primary_attempt_count=PRIMARY_ATTEMPT_THRESHOLD,
            first_detected_at=self.fixed_now - timedelta(minutes=25),
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

        incident.contingency_stage = ScraperIncident.ContingencyStage.MANUAL_REQUIRED
        incident.manual_enabled_at = self.fixed_now
        incident.save(update_fields=["contingency_stage", "manual_enabled_at", "updated_at"])

        sent = ScraperNotificationService.notify_pending_incidents(
            incidents=[incident],
            now=self.fixed_now,
        )

        self.assertEqual(sent, 1)
        incident.refresh_from_db()
        self.assertTrue(incident.alert_sent)
        mock_post.assert_called_once()

    @override_settings(
        SCRAPER_TELEGRAM_BOT_TOKEN="telegram-token",
        SCRAPER_TELEGRAM_CHAT_IDS=["1001"],
    )
    @patch("core.services.scraper_notification_service.requests.post")
    def test_notify_pending_incidents_sends_only_for_scraper_manual_required(self, mock_post):
        incident = ScraperIncident.objects.create(
            fingerprint="lotoven_animalitos|2026-03-23|scraper|-|-|missing_scraper_rows",
            scraper_key="lotoven_animalitos",
            label="Animalitos Lotoven",
            command_name="scrape_lotoven_animalitos",
            draw_date=self.draw_date,
            provider_name="",
            draw_time=None,
            result_model="AnimalitoResult",
            detection_scope="scraper",
            validation_profile="baseline",
            status=ScraperIncident.Status.OPEN,
            failure_reason_code="missing_scraper_rows",
            summary="No hay filas utilizables.",
            evidence_summary="test",
            contingency_stage=ScraperIncident.ContingencyStage.MANUAL_REQUIRED,
            manual_enabled_at=self.fixed_now,
            occurrence_count=3,
            primary_attempt_count=PRIMARY_ATTEMPT_THRESHOLD,
            first_detected_at=self.fixed_now - timedelta(minutes=25),
            last_detected_at=self.fixed_now,
        )

        incident.contingency_stage = ScraperIncident.ContingencyStage.MANUAL_REQUIRED
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
            fingerprint="lotoven_triples|2026-03-22|group|Triple Chance A|13:00|missing_expected_group",
            scraper_key="lotoven_triples",
            label="Triples Lotoven",
            command_name="scrape_lotoven_tables",
            draw_date=self.draw_date,
            provider_name="Triple Chance A",
            draw_time=datetime.strptime("13:00", "%H:%M").time(),
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
            {"provider_name": "Lotto Rey", "draw_time": "08:30", "scope": "group"},
            {"provider_name": "Mega Animal 40", "draw_time": "09:00", "scope": "group"},
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
            {"provider_name": "Lotto Rey", "draw_time": "08:30", "scope": "group"},
            {"provider_name": "Mega Animal 40", "draw_time": "09:00", "scope": "group"},
        ]
        persisted_groups = [
            {"provider_name": "Lotto Rey", "draw_time": "08:30", "scope": "group"},
            {"provider_name": "", "draw_time": "", "scope": "scraper"},
        ]
        missing_groups = [
            {"provider_name": "Mega Animal 40", "draw_time": "09:00", "scope": "group"},
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
        self.assertEqual(candidates[0].failure_reason_code, "missing_expected_group")
        self.assertEqual(candidates[0].provider_name, "Mega Animal 40")

    @override_settings(
        SCRAPER_TELEGRAM_BOT_TOKEN="telegram-token",
        SCRAPER_TELEGRAM_CHAT_IDS=["1001"],
    )
    @patch("core.services.scraper_notification_service.requests.post")
    @patch("core.services.scraper_health_service.call_command")
    def test_triples_missing_group_escalates_to_manual_after_three_attempts(self, mock_call_command, mock_post):
        def create_partial_lotoven(_command_name):
            self._seed_lotoven_results(missing_group=("Triple Caracas A", "16:30"))
            return None

        mock_call_command.side_effect = create_partial_lotoven

        with patch("core.services.scraper_health_service.timezone.now", return_value=self.fixed_now):
            with patch("core.services.scraper_execution_service.timezone.now", return_value=self.fixed_now):
                with patch("core.services.scraper_execution_service.timezone.localdate", return_value=self.draw_date):
                    for _ in range(PRIMARY_ATTEMPT_THRESHOLD):
                        ScraperHealthService.run_registered("lotoven_triples")

        incident = ScraperIncident.objects.get(
            scraper_key="lotoven_triples",
            provider_name="Triple Caracas A",
            failure_reason_code="missing_expected_group",
        )
        self.assertEqual(incident.contingency_stage, ScraperIncident.ContingencyStage.MANUAL_REQUIRED)
        self.assertEqual(incident.primary_attempt_count, PRIMARY_ATTEMPT_THRESHOLD)
        self.assertIsNotNone(incident.manual_enabled_at)
        self.assertTrue(incident.alert_sent)
        self.assertEqual(mock_post.call_count, 1)

    @override_settings(
        SCRAPER_TELEGRAM_BOT_TOKEN="telegram-token",
        SCRAPER_TELEGRAM_CHAT_IDS=["1001"],
    )
    @patch("core.services.scraper_notification_service.requests.post")
    @patch("core.services.scraper_health_service.call_command")
    def test_condor_missing_group_escalates_to_manual_after_three_attempts(self, mock_call_command, mock_post):
        def create_partial_condor(_command_name):
            self._seed_condor_results(missing_time="12:00")
            return None

        mock_call_command.side_effect = create_partial_condor

        with patch("core.services.scraper_health_service.timezone.now", return_value=self.fixed_now):
            with patch("core.services.scraper_execution_service.timezone.now", return_value=self.fixed_now):
                with patch("core.services.scraper_execution_service.timezone.localdate", return_value=self.draw_date):
                    for _ in range(PRIMARY_ATTEMPT_THRESHOLD):
                        ScraperHealthService.run_registered("condor_animalitos")

        incident = ScraperIncident.objects.get(
            scraper_key="condor_animalitos",
            provider_name="Condor Gana",
            draw_time=datetime.strptime("12:00", "%H:%M").time(),
            failure_reason_code="missing_expected_group",
        )
        self.assertEqual(incident.contingency_stage, ScraperIncident.ContingencyStage.MANUAL_REQUIRED)
        self.assertEqual(incident.primary_attempt_count, PRIMARY_ATTEMPT_THRESHOLD)
        self.assertIsNotNone(incident.manual_enabled_at)
        self.assertTrue(incident.alert_sent)
        self.assertEqual(mock_post.call_count, 1)

    @override_settings(
        SCRAPER_TELEGRAM_BOT_TOKEN="telegram-token",
        SCRAPER_TELEGRAM_CHAT_IDS=["1001"],
    )
    @patch("core.services.scraper_notification_service.requests.post")
    @patch("core.services.scraper_execution_service.TuAzarAnimalitoFallbackService.run_lottorey")
    @patch("core.services.scraper_health_service.call_command")
    def test_lottorey_missing_provider_activates_fallback_after_three_attempts(
        self,
        mock_call_command,
        mock_run_fallback,
        mock_post,
    ):
        def create_partial_rows(_command_name):
            self._seed_lotoven_animalitos_results(missing_provider="Lotto Rey")
            return None

        mock_call_command.side_effect = create_partial_rows
        mock_run_fallback.return_value = FallbackAttemptResult(
            scraper_key=TuAzarAnimalitoFallbackService.SCRAPER_KEY,
            provider_name="Lotto Rey",
            rows_persisted=3,
            success=True,
            detail="fallback ok",
        )

        with patch("core.services.scraper_health_service.timezone.now", return_value=self.fixed_now):
            with patch("core.services.scraper_execution_service.timezone.now", return_value=self.fixed_now):
                with patch("core.services.scraper_execution_service.timezone.localdate", return_value=self.draw_date):
                    for _ in range(PRIMARY_ATTEMPT_THRESHOLD):
                        ScraperHealthService.run_registered("lotoven_animalitos")

        incident = ScraperIncident.objects.get(
            scraper_key="lotoven_animalitos",
            provider_name="Lotto Rey",
            draw_time=datetime.strptime("19:30", "%H:%M").time(),
            failure_reason_code="missing_expected_group",
        )
        self.assertEqual(incident.contingency_stage, ScraperIncident.ContingencyStage.FALLBACK_ACTIVE)
        self.assertEqual(incident.primary_attempt_count, PRIMARY_ATTEMPT_THRESHOLD)
        self.assertEqual(incident.fallback_attempt_count, 0)
        self.assertEqual(incident.fallback_scraper_key, TuAzarAnimalitoFallbackService.SCRAPER_KEY)
        self.assertIsNotNone(incident.fallback_activated_at)
        self.assertTrue(incident.alert_sent)
        self.assertEqual(mock_run_fallback.call_count, 1)
        self.assertEqual(mock_post.call_count, 1)

    @override_settings(
        SCRAPER_TELEGRAM_BOT_TOKEN="telegram-token",
        SCRAPER_TELEGRAM_CHAT_IDS=["1001"],
    )
    @patch("core.services.scraper_notification_service.requests.post")
    @patch("core.services.scraper_execution_service.TuAzarAnimalitoFallbackService.run_lottorey")
    @patch("core.services.scraper_health_service.call_command")
    def test_lottorey_missing_provider_escalates_to_manual_after_fallback_exhaustion(
        self,
        mock_call_command,
        mock_run_fallback,
        mock_post,
    ):
        def create_partial_rows(_command_name):
            self._seed_lotoven_animalitos_results(missing_provider="Lotto Rey")
            return None

        mock_call_command.side_effect = create_partial_rows
        mock_run_fallback.return_value = FallbackAttemptResult(
            scraper_key=TuAzarAnimalitoFallbackService.SCRAPER_KEY,
            provider_name="Lotto Rey",
            rows_persisted=0,
            success=False,
            detail="sin filas en fallback",
        )

        total_runs = PRIMARY_ATTEMPT_THRESHOLD + FALLBACK_ATTEMPT_THRESHOLD - 1
        with patch("core.services.scraper_health_service.timezone.now", return_value=self.fixed_now):
            with patch("core.services.scraper_execution_service.timezone.now", return_value=self.fixed_now):
                with patch("core.services.scraper_execution_service.timezone.localdate", return_value=self.draw_date):
                    for _ in range(total_runs):
                        ScraperHealthService.run_registered("lotoven_animalitos")

        incident = ScraperIncident.objects.get(
            scraper_key="lotoven_animalitos",
            provider_name="Lotto Rey",
            draw_time=datetime.strptime("19:30", "%H:%M").time(),
            failure_reason_code="missing_expected_group",
        )
        self.assertEqual(incident.contingency_stage, ScraperIncident.ContingencyStage.MANUAL_REQUIRED)
        self.assertEqual(incident.primary_attempt_count, PRIMARY_ATTEMPT_THRESHOLD)
        self.assertEqual(incident.fallback_attempt_count, FALLBACK_ATTEMPT_THRESHOLD)
        self.assertIsNotNone(incident.manual_enabled_at)
        self.assertTrue(incident.alert_sent)
        self.assertEqual(mock_run_fallback.call_count, FALLBACK_ATTEMPT_THRESHOLD)
        self.assertEqual(mock_post.call_count, 2)
