from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.forms import ScraperIncidentManualResolutionForm
from core.models import (
    AnimalitoResult,
    CurrentResult,
    ManualResultIntervention,
    Provider,
    ScraperIncident,
)
from core.services.manual_result_intervention_service import ManualResultInterventionService
from core.services.scraper_execution_service import LOTOVEN_TABLE_SIMPLE_PROVIDERS, LOTOVEN_STRICT_SCHEDULE
from core.services.scraper_health_service import ScraperHealthService


class ManualIncidentResolutionServiceTestCase(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="ops-admin",
            email="ops@example.com",
            password="secret123",
        )
        self.provider = Provider.objects.create(
            name="Triple Chance A",
            source_url="https://lotoven.com",
            is_active=True,
        )
        self.incident = ScraperIncident.objects.create(
            fingerprint="lotoven_triples|2026-03-23|group|Triple Chance A|16:00|missing_expected_group",
            scraper_key="lotoven_triples",
            label="Triples Lotoven",
            command_name="scrape_lotoven_tables",
            draw_date=datetime(2026, 3, 23).date(),
            provider_name="Triple Chance A",
            draw_time=datetime.strptime("16:00", "%H:%M").time(),
            result_model="CurrentResult",
            detection_scope="group",
            validation_profile="mixed",
            failure_reason_code="missing_expected_group",
            summary="Falta el grupo esperado Triple Chance A 16:00.",
            evidence_summary="expected=1 persisted=0 missing=1",
            contingency_stage=ScraperIncident.ContingencyStage.MANUAL_REQUIRED,
            manual_enabled_at=timezone.now(),
        )

    def test_manual_resolution_replaces_result_and_resolves_incident(self):
        existing = CurrentResult.objects.create(
            provider=self.provider,
            draw_date=self.incident.draw_date,
            draw_time=self.incident.draw_time,
            winning_number="111",
            image_url="",
            extra=None,
        )

        intervention = ManualResultInterventionService.resolve_incident_manually(
            incident=self.incident,
            user=self.user,
            cleaned_data={
                "provider": self.provider,
                "draw_time": self.incident.draw_time,
                "winning_number": "222",
                "signo": "ARIES",
                "note": "Validado con fuente oficial de contingencia.",
            },
        )

        existing.refresh_from_db()
        self.incident.refresh_from_db()

        self.assertEqual(existing.winning_number, "222")
        self.assertEqual(existing.image_url, "")
        self.assertEqual(existing.extra, {"signo": "ARIES"})
        self.assertEqual(existing.result_origin, CurrentResult.ResultOrigin.MANUAL_CONTINGENCY)
        self.assertEqual(existing.source_incident_id, self.incident.id)

        self.assertEqual(intervention.action_type, ManualResultIntervention.ActionType.REPLACE)
        self.assertEqual(intervention.previous_snapshot["winning_number"], "111")
        self.assertEqual(intervention.new_snapshot["winning_number"], "222")
        self.assertEqual(intervention.performed_by, self.user)

        self.assertEqual(self.incident.status, ScraperIncident.Status.RESOLVED)
        self.assertEqual(self.incident.resolved_by, self.user)
        self.assertIsNotNone(self.incident.resolved_at)
        self.assertIn("Intervention", self.incident.resolution_note)

    def test_manual_resolution_preserves_existing_image_url_for_current_results(self):
        existing = CurrentResult.objects.create(
            provider=self.provider,
            draw_date=self.incident.draw_date,
            draw_time=self.incident.draw_time,
            winning_number="111",
            image_url="https://example.com/existing.png",
            extra=None,
        )

        ManualResultInterventionService.resolve_incident_manually(
            incident=self.incident,
            user=self.user,
            cleaned_data={
                "provider": self.provider,
                "draw_time": self.incident.draw_time,
                "winning_number": "333",
                "signo": "",
                "note": "Correccion manual sin tocar imagen.",
            },
        )

        existing.refresh_from_db()
        self.assertEqual(existing.winning_number, "333")
        self.assertEqual(existing.image_url, "https://example.com/existing.png")


class ManualIncidentResolutionFormTestCase(TestCase):
    def test_current_result_form_hides_image_url_field(self):
        incident = ScraperIncident.objects.create(
            fingerprint="lotoven_triples|2026-03-23|group|Triple Chance A|16:00|missing_expected_group",
            scraper_key="lotoven_triples",
            label="Triples Lotoven",
            command_name="scrape_lotoven_tables",
            draw_date=datetime(2026, 3, 23).date(),
            provider_name="Triple Chance A",
            draw_time=datetime.strptime("16:00", "%H:%M").time(),
            result_model="CurrentResult",
            detection_scope="group",
            validation_profile="mixed",
            failure_reason_code="missing_expected_group",
            summary="Falta el grupo esperado Triple Chance A 16:00.",
            evidence_summary="expected=1 persisted=0 missing=1",
            contingency_stage=ScraperIncident.ContingencyStage.MANUAL_REQUIRED,
            manual_enabled_at=timezone.now(),
        )

        form = ScraperIncidentManualResolutionForm(incident=incident)

        self.assertNotIn("image_url", form.fields)
        self.assertIn("winning_number", form.fields)

    def test_animalito_form_hides_image_url_fields(self):
        incident = ScraperIncident.objects.create(
            fingerprint="condor_animalitos|2026-03-23|group|Condor Gana|09:00|missing_expected_group",
            scraper_key="condor_animalitos",
            label="Animalitos Condor Gana",
            command_name="scrape_condor_animalitos",
            draw_date=datetime(2026, 3, 23).date(),
            provider_name="Condor Gana",
            draw_time=datetime.strptime("09:00", "%H:%M").time(),
            result_model="AnimalitoResult",
            detection_scope="group",
            validation_profile="baseline",
            failure_reason_code="missing_expected_group",
            summary="Falta Condor Gana 09:00.",
            evidence_summary="expected=1 persisted=0 missing=1",
            contingency_stage=ScraperIncident.ContingencyStage.MANUAL_REQUIRED,
            manual_enabled_at=timezone.now(),
        )

        form = ScraperIncidentManualResolutionForm(incident=incident)

        self.assertNotIn("animal_image_url", form.fields)
        self.assertNotIn("provider_logo_url", form.fields)
        self.assertIn("animal_number", form.fields)
        self.assertIn("animal_name", form.fields)


class ManualIncidentResolutionAdminFlowTestCase(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="ops-admin-2",
            email="ops2@example.com",
            password="secret123",
        )
        self.provider = Provider.objects.create(
            name="Condor Gana",
            source_url="https://www.lottoresultados.com/resultados/animalitos/condor-gana",
            is_active=True,
            logo_url="https://example.com/provider-logo.png",
        )
        self.incident = ScraperIncident.objects.create(
            fingerprint="condor_animalitos|2026-03-23|group|Condor Gana|09:00|missing_expected_group",
            scraper_key="condor_animalitos",
            label="Animalitos Condor Gana",
            command_name="scrape_condor_animalitos",
            draw_date=datetime(2026, 3, 23).date(),
            provider_name="Condor Gana",
            draw_time=datetime.strptime("09:00", "%H:%M").time(),
            result_model="AnimalitoResult",
            detection_scope="group",
            validation_profile="baseline",
            failure_reason_code="missing_expected_group",
            summary="Falta Condor Gana 09:00.",
            evidence_summary="expected=1 persisted=0 missing=1",
            contingency_stage=ScraperIncident.ContingencyStage.MANUAL_REQUIRED,
            manual_enabled_at=timezone.now(),
        )
        self.client.force_login(self.user)

    def test_admin_manual_resolution_flow_creates_intervention_and_resolves_incident(self):
        url = reverse("admin:core_scraperincident_manual_resolve", args=[self.incident.pk])

        response = self.client.post(
            url,
            data={
                "provider": self.provider.pk,
                "draw_date": self.incident.draw_date.isoformat(),
                "draw_time": "09:00",
                "animal_number": "07",
                "animal_name": "Perico",
                "note": "Carga manual por contingencia validada.",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.incident.refresh_from_db()

        result = AnimalitoResult.objects.get(
            provider=self.provider,
            draw_date=self.incident.draw_date,
            draw_time=self.incident.draw_time,
        )
        self.assertEqual(result.result_origin, AnimalitoResult.ResultOrigin.MANUAL_CONTINGENCY)
        self.assertEqual(result.source_incident_id, self.incident.id)
        self.assertEqual(result.animal_number, "07")
        self.assertEqual(result.animal_name, "Perico")
        self.assertEqual(result.animal_image_url, "")
        self.assertEqual(result.provider_logo_url, "https://example.com/provider-logo.png")

        intervention = ManualResultIntervention.objects.get(incident=self.incident)
        self.assertEqual(intervention.action_type, ManualResultIntervention.ActionType.CREATE)
        self.assertEqual(intervention.performed_by, self.user)
        self.assertEqual(intervention.new_snapshot["animal_name"], "Perico")

        self.assertEqual(self.incident.status, ScraperIncident.Status.RESOLVED)
        self.assertEqual(self.incident.resolved_by, self.user)
        self.assertTrue(self.incident.resolution_note)


class ManualResolutionReopenFlowTestCase(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="ops-admin-3",
            email="ops3@example.com",
            password="secret123",
        )
        self.fixed_now = timezone.make_aware(datetime(2026, 3, 23, 20, 0, 0), timezone.get_current_timezone())
        self.draw_date = self.fixed_now.date()

    def _upsert_provider(self, name: str) -> Provider:
        provider, _ = Provider.objects.get_or_create(
            name=name,
            defaults={"source_url": "https://lotoven.com", "is_active": True, "logo_url": ""},
        )
        return provider

    def _seed_partial_automatic_rows(self):
        for provider_name in LOTOVEN_TABLE_SIMPLE_PROVIDERS:
            provider = self._upsert_provider(provider_name)
            CurrentResult.objects.update_or_create(
                provider=provider,
                draw_date=self.draw_date,
                draw_time=datetime.strptime("08:00", "%H:%M").time(),
                defaults={"winning_number": "111"},
            )

        for provider_name, times in LOTOVEN_STRICT_SCHEDULE.items():
            provider = self._upsert_provider(provider_name)
            for time_str in times:
                if (provider_name, time_str) == ("Triple Caracas A", "16:30"):
                    continue
                CurrentResult.objects.update_or_create(
                    provider=provider,
                    draw_date=self.draw_date,
                    draw_time=datetime.strptime(time_str, "%H:%M").time(),
                    defaults={"winning_number": "222"},
                )

    @override_settings(
        SCRAPER_TELEGRAM_BOT_TOKEN="telegram-token",
        SCRAPER_TELEGRAM_CHAT_IDS=["1001"],
    )
    @patch("core.services.scraper_notification_service.requests.post")
    @patch("core.services.scraper_health_service.call_command")
    def test_manual_resolution_keeps_incident_resolved_when_manual_result_is_still_served(self, mock_call_command, mock_post):
        def partial_rows(_command_name):
            self._seed_partial_automatic_rows()
            return None

        mock_call_command.side_effect = partial_rows

        with patch("core.services.scraper_health_service.timezone.now", return_value=self.fixed_now):
            with patch("core.services.scraper_execution_service.timezone.now", return_value=self.fixed_now):
                with patch("core.services.scraper_execution_service.timezone.localdate", return_value=self.draw_date):
                    ScraperHealthService.run_registered("lotoven_triples")

        incident = ScraperIncident.objects.get(
            scraper_key="lotoven_triples",
            provider_name="Triple Caracas A",
            failure_reason_code="missing_expected_group",
        )
        incident.contingency_stage = ScraperIncident.ContingencyStage.MANUAL_REQUIRED
        incident.manual_enabled_at = self.fixed_now
        incident.save(update_fields=["contingency_stage", "manual_enabled_at", "updated_at"])
        provider = Provider.objects.get(name="Triple Caracas A")

        ManualResultInterventionService.resolve_incident_manually(
            incident=incident,
            user=self.user,
            cleaned_data={
                "provider": provider,
                "draw_time": datetime.strptime("16:30", "%H:%M").time(),
                "winning_number": "555",
                "signo": "",
                "image_url": "",
                "note": "Carga manual temporal.",
            },
        )

        incident.refresh_from_db()
        self.assertEqual(incident.status, ScraperIncident.Status.RESOLVED)

        with patch("core.services.scraper_health_service.timezone.now", return_value=self.fixed_now):
            with patch("core.services.scraper_execution_service.timezone.now", return_value=self.fixed_now):
                with patch("core.services.scraper_execution_service.timezone.localdate", return_value=self.draw_date):
                    ScraperHealthService.run_registered("lotoven_triples")

        incident.refresh_from_db()
        self.assertEqual(incident.status, ScraperIncident.Status.RESOLVED)
        self.assertEqual(incident.occurrence_count, 1)
        self.assertEqual(mock_post.call_count, 0)


class ScraperPermissionServiceTestCase(TestCase):
    @override_settings(
        SCRAPER_INCIDENT_VIEWER_GROUPS=["ScraperViewers"],
        SCRAPER_INCIDENT_RESOLVER_GROUPS=["ScraperResolvers"],
    )
    def test_manual_resolution_view_requires_resolver_group(self):
        user_model = get_user_model()
        viewer_group = Group.objects.create(name="ScraperViewers")
        resolver_group = Group.objects.create(name="ScraperResolvers")

        viewer = user_model.objects.create_user(
            username="viewer-user",
            email="viewer@example.com",
            password="secret123",
            is_staff=True,
        )
        viewer.groups.add(viewer_group)

        resolver = user_model.objects.create_user(
            username="resolver-user",
            email="resolver@example.com",
            password="secret123",
            is_staff=True,
        )
        resolver.groups.add(resolver_group)

        provider = Provider.objects.create(
            name="Condor Gana",
            source_url="https://www.lottoresultados.com/resultados/animalitos/condor-gana",
            is_active=True,
        )
        incident = ScraperIncident.objects.create(
            fingerprint="perm|condor|2026-03-23|09:00",
            scraper_key="condor_animalitos",
            label="Animalitos Condor Gana",
            command_name="scrape_condor_animalitos",
            draw_date=datetime(2026, 3, 23).date(),
            provider_name=provider.name,
            draw_time=datetime.strptime("09:00", "%H:%M").time(),
            result_model="AnimalitoResult",
            detection_scope="group",
            validation_profile="baseline",
            failure_reason_code="missing_expected_group",
            summary="Falta grupo.",
            evidence_summary="expected=1 persisted=0 missing=1",
            contingency_stage=ScraperIncident.ContingencyStage.MANUAL_REQUIRED,
            manual_enabled_at=timezone.now(),
        )

        url = reverse("admin:core_scraperincident_manual_resolve", args=[incident.pk])

        self.client.force_login(viewer)
        viewer_response = self.client.get(url)
        self.assertEqual(viewer_response.status_code, 403)

        self.client.force_login(resolver)
        resolver_response = self.client.get(url)
        self.assertEqual(resolver_response.status_code, 200)
