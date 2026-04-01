from __future__ import annotations

from decimal import Decimal
from datetime import date, datetime, timedelta
from tempfile import NamedTemporaryFile
from unittest.mock import call, patch

from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from core.models import (
    AnimalitoResult,
    Branch,
    Client,
    CruzDailyContent,
    CurrentResult,
    Device,
    DeviceTelemetryEvent,
    DeviceTelemetrySnapshot,
    Provider,
    ScraperExecution,
    ScraperHealth,
    Transmission,
)
from core.services.device_telemetry_service import DeviceTelemetryService
from core.services.provider_catalog_service import (
    canonical_animalito_provider_name,
    is_visible_animalito_provider,
)
from core.services.result_window_service import delete_future_rows_for_provider
from core.services.scraper_notification_service import ScraperNotificationService
from core.services.scraper_health_service import ScraperHealthService


TEST_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "telemetry-tests",
    }
}

TEST_CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}


class AnimalitoProviderCatalogTestCase(TestCase):
    def test_canonical_name_maps_known_aliases(self):
        self.assertEqual(canonical_animalito_provider_name("Mega Animal"), "Mega Animal 40")
        self.assertEqual(canonical_animalito_provider_name("Mega Animal 40"), "Mega Animal 40")
        self.assertEqual(canonical_animalito_provider_name("Loto Rey"), "Lotto Rey")
        self.assertEqual(canonical_animalito_provider_name("El Guácharo"), "Guacharo")
        self.assertEqual(canonical_animalito_provider_name("Condor Gana"), "Condor Gana")

    def test_visible_provider_check_accepts_catalog_aliases(self):
        self.assertTrue(is_visible_animalito_provider("Mega Animal"))
        self.assertTrue(is_visible_animalito_provider("Mega Animal 40"))
        self.assertTrue(is_visible_animalito_provider("Loto Rey"))
        self.assertTrue(is_visible_animalito_provider("El Guacharito"))
        self.assertTrue(is_visible_animalito_provider("Condor Gana"))


@override_settings(CACHES=TEST_CACHES, CHANNEL_LAYERS=TEST_CHANNEL_LAYERS)
class DeviceTelemetryAPITestCase(TestCase):
    def setUp(self):
        self.client_model = Client.objects.create(name="Cliente QA")
        self.branch = Branch.objects.create(
            client=self.client_model,
            name="Sucursal QA",
            is_active=True,
            paid_until=timezone.now() + timedelta(days=30),
        )
        self.device = Device.objects.create(
            device_id="tv-qa-001",
            activation_code="COD123",
            is_active=True,
            branch=self.branch,
        )

    def test_heartbeat_updates_snapshot_and_device_status(self):
        response = self.client.post(
            "/api/devices/heartbeat/",
            data={"device_id": self.device.device_id, "code": self.device.activation_code},
            content_type="application/json",
            REMOTE_ADDR="10.10.10.20",
        )

        self.assertEqual(response.status_code, 200)

        self.device.refresh_from_db()
        snapshot = self.device.telemetry_snapshot
        self.assertIsNotNone(snapshot.last_heartbeat_at)
        self.assertEqual(snapshot.last_ip_address, "10.10.10.20")

    def test_telemetry_endpoint_creates_event_and_updates_snapshot(self):
        response = self.client.post(
            "/api/devices/telemetry/",
            data={
                "device_id": self.device.device_id,
                "code": self.device.activation_code,
                "event_type": "LOAD_ERROR",
                "message": "net::ERR_CONNECTION_TIMED_OUT",
                "metadata": {
                    "android_version": "9",
                    "webview_version": "69.0",
                    "device_model": "SMART_TV_CHINA",
                },
            },
            content_type="application/json",
            REMOTE_ADDR="10.10.10.20",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(DeviceTelemetryEvent.objects.count(), 1)

        event = DeviceTelemetryEvent.objects.get()
        self.assertEqual(event.event_type, "LOAD_ERROR")
        self.assertEqual(event.ip_address, "10.10.10.20")

        snapshot = self.device.telemetry_snapshot
        self.assertEqual(snapshot.last_error_reported_message, "net::ERR_CONNECTION_TIMED_OUT")
        self.assertEqual(snapshot.android_version, "9")
        self.assertEqual(snapshot.webview_version, "69.0")
        self.assertEqual(snapshot.device_model, "SMART_TV_CHINA")

    def test_telemetry_requires_matching_device_id(self):
        response = self.client.post(
            "/api/devices/telemetry/",
            data={
                "device_id": "otro-device",
                "code": self.device.activation_code,
                "event_type": "LOW_MEMORY",
            },
            content_type="application/json",
            REMOTE_ADDR="10.10.10.20",
        )

        self.assertEqual(response.status_code, 403)

    def test_load_success_updates_snapshot_without_persisting_event(self):
        response = self.client.post(
            "/api/devices/telemetry/",
            data={
                "device_id": self.device.device_id,
                "code": self.device.activation_code,
                "event_type": "LOAD_SUCCESS",
                "message": "render ok",
            },
            content_type="application/json",
            REMOTE_ADDR="10.10.10.20",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(DeviceTelemetryEvent.objects.count(), 0)
        self.assertEqual(response.json()["persisted"], False)

        snapshot = self.device.telemetry_snapshot
        self.assertIsNotNone(snapshot.last_load_success_at)

@override_settings(
    CACHES=TEST_CACHES,
    CHANNEL_LAYERS=TEST_CHANNEL_LAYERS,
    SCRAPER_TELEGRAM_BOT_TOKEN="",
    SCRAPER_TELEGRAM_CHAT_IDS=[],
)
class ScraperHealthServiceTestCase(TestCase):
    @patch("core.services.scraper_health_service.call_command")
    def test_run_registered_success_marks_monitor(self, mock_call_command):
        def seed_condor_result(_command_name):
            provider = Provider.objects.create(
                name="Condor Gana",
                source_url="https://www.lottoresultados.com/resultados/animalitos/condor-gana",
                is_active=True,
            )
            AnimalitoResult.objects.create(
                provider=provider,
                draw_date=timezone.localdate(),
                draw_time=datetime.strptime("09:00", "%H:%M").time(),
                animal_number="62",
                animal_name="Cachicamo",
                animal_image_url="https://example.com/condor-62.webp",
                provider_logo_url="https://example.com/condor-logo.webp",
            )
            return None

        mock_call_command.side_effect = seed_condor_result

        ScraperHealthService.run_registered("condor_animalitos")

        monitor = ScraperHealth.objects.get(scraper_key="condor_animalitos")
        self.assertEqual(monitor.last_status, ScraperHealth.Status.SUCCESS)
        self.assertEqual(monitor.command_name, "scrape_condor_animalitos")
        self.assertEqual(monitor.consecutive_failures, 0)
        self.assertIsNotNone(monitor.last_success_at)
        mock_call_command.assert_called_once_with("scrape_condor_animalitos")

    @patch("core.services.scraper_health_service.call_command")
    def test_run_registered_failure_marks_monitor(self, mock_call_command):
        mock_call_command.side_effect = RuntimeError("condor parser failed")

        with self.assertRaises(RuntimeError):
            ScraperHealthService.run_registered("condor_animalitos")

        monitor = ScraperHealth.objects.get(scraper_key="condor_animalitos")
        self.assertEqual(monitor.last_status, ScraperHealth.Status.FAILED)
        self.assertEqual(monitor.consecutive_failures, 1)
        self.assertIn("condor parser failed", monitor.last_error_message)

    def test_get_alert_marks_failed_today(self):
        now = timezone.now()
        monitor = ScraperHealthService.get_or_create_monitor("condor_animalitos")
        monitor.last_status = ScraperHealth.Status.FAILED
        monitor.last_started_at = now
        monitor.last_finished_at = now
        monitor.last_error_message = "condor parser failed"
        monitor.consecutive_failures = 1
        monitor.save(
            update_fields=[
                "last_status",
                "last_started_at",
                "last_finished_at",
                "last_error_message",
                "consecutive_failures",
                "updated_at",
            ]
        )

        alert = ScraperHealthService.get_alert("condor_animalitos", now=now)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["alert_kind"], "failed_today")

    def test_get_alert_marks_stale(self):
        now = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
        monitor = ScraperHealthService.get_or_create_monitor("condor_animalitos")
        monitor.last_status = ScraperHealth.Status.SUCCESS
        monitor.last_success_at = now - timedelta(minutes=200)
        monitor.last_finished_at = monitor.last_success_at
        monitor.save(
            update_fields=[
                "last_status",
                "last_success_at",
                "last_finished_at",
                "updated_at",
            ]
        )

        alert = ScraperHealthService.get_alert("condor_animalitos", now=now)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["alert_kind"], "stale")

    def test_get_alert_respects_min_failures_threshold_for_tuazar(self):
        now = timezone.now()
        monitor = ScraperHealthService.get_or_create_monitor("tuazar_triples")
        monitor.last_status = ScraperHealth.Status.FAILED
        monitor.last_started_at = now
        monitor.last_finished_at = now
        monitor.last_error_message = "Triple Gana no dejo filas utilizables hoy."
        monitor.consecutive_failures = 2
        monitor.save(
            update_fields=[
                "last_status",
                "last_started_at",
                "last_finished_at",
                "last_error_message",
                "consecutive_failures",
                "updated_at",
            ]
        )

        alert = ScraperHealthService.get_alert("tuazar_triples", now=now)
        self.assertIsNone(alert)


class ScraperNotificationServiceTestCase(TestCase):
    @override_settings(
        SCRAPER_TELEGRAM_BOT_TOKEN="telegram-token",
        SCRAPER_TELEGRAM_CHAT_IDS=["1001"],
    )
    @patch("core.services.scraper_notification_service.requests.post")
    def test_notify_active_alerts_sends_telegram_and_marks_monitor(self, mock_post):
        monitor = ScraperHealthService.get_or_create_monitor("condor_animalitos")
        now = timezone.now()
        monitor.last_status = ScraperHealth.Status.FAILED
        monitor.last_started_at = now
        monitor.last_finished_at = now
        monitor.last_error_message = "condor parser failed"
        monitor.consecutive_failures = 1
        monitor.save(
            update_fields=[
                "last_status",
                "last_started_at",
                "last_finished_at",
                "last_error_message",
                "consecutive_failures",
                "updated_at",
            ]
        )

        sent = ScraperNotificationService.notify_active_alerts(now=now, monitors=[monitor])

        self.assertEqual(sent, 1)
        mock_post.assert_called_once()


@override_settings(CACHES=TEST_CACHES, CHANNEL_LAYERS=TEST_CHANNEL_LAYERS, WEEKLY_DEVICE_RATE_USD="3")
class WeeklyDeviceReportAdminTestCase(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="billing-admin",
            email="billing@example.com",
            password="secret123",
        )
        self.client_model = Client.objects.create(name="Cliente Billing")
        self.active_branch = Branch.objects.create(
            client=self.client_model,
            name="Sucursal Activa",
            is_active=True,
            paid_until=timezone.now() + timedelta(days=7),
        )
        self.inactive_branch = Branch.objects.create(
            client=self.client_model,
            name="Sucursal Inactiva",
            is_active=False,
            paid_until=timezone.now() + timedelta(days=7),
        )
        Device.objects.create(
            device_id="tv-billing-001",
            activation_code="BILL01",
            is_active=True,
            branch=self.active_branch,
        )
        Device.objects.create(
            device_id="tv-billing-002",
            activation_code="BILL02",
            is_active=True,
            branch=self.inactive_branch,
        )
        Device.objects.create(
            device_id="tv-billing-003",
            activation_code="BILL03",
            is_active=False,
            branch=self.active_branch,
        )
        second_group_start = timezone.now() + timedelta(days=7)
        self.second_group_branch = Branch.objects.create(
            client=self.client_model,
            name="Sucursal Segundo Grupo",
            is_active=True,
            membership_started_at=second_group_start,
            paid_until=second_group_start + timedelta(days=7),
        )
        Device.objects.create(
            device_id="tv-billing-004",
            activation_code="BILL04",
            is_active=True,
            branch=self.second_group_branch,
        )

    def test_weekly_report_admin_shows_only_operational_devices(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("admin:core_weeklydevicereport_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cliente Billing")
        self.assertContains(response, "BILL01")
        self.assertContains(response, "BILL04")
        self.assertNotContains(response, "BILL02")
        self.assertNotContains(response, "BILL03")
        self.assertEqual(response.context["summary"]["device_count"], 2)
        self.assertEqual(response.context["summary"]["weekly_total_usd"], Decimal("6"))
        self.assertContains(response, self.active_branch.paid_until.strftime("%Y-%m-%d"))
        self.assertContains(response, self.active_branch.membership_started_at.strftime("%Y-%m-%d"))
        self.assertContains(response, self.second_group_branch.paid_until.strftime("%Y-%m-%d"))
        client_row = response.context["report_rows"][0]
        self.assertEqual(len(client_row["membership_groups"]), 2)
        self.assertEqual(
            sorted(group["weekly_total_usd"] for group in client_row["membership_groups"]),
            [Decimal("3"), Decimal("3")],
        )


class BranchMembershipWindowTestCase(TestCase):
    def test_branch_sets_membership_started_at_from_current_window(self):
        client = Client.objects.create(name="Cliente Membresia")
        paid_until = timezone.now() + timedelta(days=7)

        branch = Branch.objects.create(
            client=client,
            name="Sucursal Membresia",
            paid_until=paid_until,
        )

        self.assertIsNotNone(branch.membership_started_at)
        self.assertEqual(branch.membership_started_at, paid_until - timedelta(days=7))

    def test_branch_extension_moves_membership_started_at_to_previous_paid_until(self):
        client = Client.objects.create(name="Cliente Extension")
        initial_paid_until = timezone.now() + timedelta(days=7)
        branch = Branch.objects.create(
            client=client,
            name="Sucursal Extension",
            paid_until=initial_paid_until,
        )

        previous_paid_until = branch.paid_until
        branch.paid_until = previous_paid_until + timedelta(days=7)
        branch.save()

        self.assertEqual(branch.membership_started_at, previous_paid_until)


class WarmScraperDataCommandTestCase(TestCase):
    @patch("core.management.commands.warm_scraper_data.ScraperHealthService.run_registered")
    def test_warm_scraper_data_runs_when_last_success_is_stale(self, mock_run_registered):
        fixed_now = timezone.make_aware(
            datetime(2026, 3, 29, 12, 0, 0),
            timezone.get_current_timezone(),
        )
        definition = ScraperHealthService.get_definition("lotoven_animalitos")
        monitor = ScraperHealthService.get_or_create_monitor("lotoven_animalitos")
        monitor.last_status = ScraperHealth.Status.SUCCESS
        monitor.last_success_at = fixed_now - timedelta(hours=4)
        monitor.save(update_fields=["last_status", "last_success_at", "updated_at"])

        with patch.dict(ScraperHealthService.REGISTRY, {"lotoven_animalitos": definition}, clear=True):
            with patch("core.management.commands.warm_scraper_data.timezone.now", return_value=fixed_now):
                call_command("warm_scraper_data", max_age_minutes=90)

        mock_run_registered.assert_called_once_with("lotoven_animalitos")

    @patch("core.management.commands.warm_scraper_data.ScraperHealthService.run_registered")
    def test_warm_scraper_data_skips_when_last_success_is_recent(self, mock_run_registered):
        fixed_now = timezone.make_aware(
            datetime(2026, 3, 29, 12, 0, 0),
            timezone.get_current_timezone(),
        )
        definition = ScraperHealthService.get_definition("condor_animalitos")
        monitor = ScraperHealthService.get_or_create_monitor("condor_animalitos")
        monitor.last_status = ScraperHealth.Status.SUCCESS
        monitor.last_success_at = fixed_now - timedelta(minutes=20)
        monitor.save(update_fields=["last_status", "last_success_at", "updated_at"])

        with patch.dict(ScraperHealthService.REGISTRY, {"condor_animalitos": definition}, clear=True):
            with patch("core.management.commands.warm_scraper_data.timezone.now", return_value=fixed_now):
                call_command("warm_scraper_data", max_age_minutes=90)

        mock_run_registered.assert_not_called()

    @patch("core.management.commands.warm_scraper_data.call_command")
    def test_warm_scraper_data_runs_cruz_daily_when_missing_for_today(self, mock_call_command):
        fixed_now = timezone.make_aware(
            datetime(2026, 3, 29, 12, 0, 0),
            timezone.get_current_timezone(),
        )

        with patch.dict(ScraperHealthService.REGISTRY, {}, clear=True):
            with patch("core.management.commands.warm_scraper_data.timezone.now", return_value=fixed_now):
                call_command("warm_scraper_data", max_age_minutes=90)

        mock_call_command.assert_called_once_with("scrape_cruz_daily_content")

    @patch("core.management.commands.warm_scraper_data.call_command")
    def test_warm_scraper_data_skips_cruz_daily_before_six_am(self, mock_call_command):
        fixed_now = timezone.make_aware(
            datetime(2026, 3, 29, 5, 59, 0),
            timezone.get_current_timezone(),
        )

        with patch.dict(ScraperHealthService.REGISTRY, {}, clear=True):
            with patch("core.management.commands.warm_scraper_data.timezone.now", return_value=fixed_now):
                call_command("warm_scraper_data", max_age_minutes=90)

        mock_call_command.assert_not_called()

    @patch("core.management.commands.warm_scraper_data.call_command")
    def test_warm_scraper_data_skips_cruz_daily_when_today_exists(self, mock_call_command):
        fixed_now = timezone.make_aware(
            datetime(2026, 3, 29, 12, 0, 0),
            timezone.get_current_timezone(),
        )
        CruzDailyContent.objects.create(
            draw_date=fixed_now.date(),
            card_type=CruzDailyContent.CardType.CRUCETA,
            title="Cruceta de Hoy",
            image_url="https://example.com/cruceta.jpg",
            display_order=0,
        )

        with patch.dict(ScraperHealthService.REGISTRY, {}, clear=True):
            with patch("core.management.commands.warm_scraper_data.timezone.now", return_value=fixed_now):
                call_command("warm_scraper_data", max_age_minutes=90)

        mock_call_command.assert_not_called()


class CruzDailyContentCommandTestCase(TestCase):
    def test_scrape_cruz_daily_content_keeps_only_current_draw_date(self):
        CruzDailyContent.objects.create(
            draw_date=date(2026, 3, 28),
            card_type=CruzDailyContent.CardType.CRUCETA,
            title="Vieja Cruceta",
            image_url="https://example.com/old.jpg",
            display_order=0,
        )

        html = """
        <div class="row mb-3">
          <div class="col-md-4 mb-3">
            <div class="card bg-primary text-white">
              <div class="card-body">
                <h2 class="card-title">Cruceta de Hoy</h2>
                <img alt="cruz de la suerte hoy 29/3/2026" src="/img/cruzdelasuerte_29-03-2026.jpg">
              </div>
            </div>
          </div>
          <div class="col-md-4 mb-3">
            <div class="card bg-primary text-white">
              <div class="card-body">
                <h2 class="card-title">Guía y Probables</h2>
                <img alt="Numeros probables de hoy 29/3/2026" src="/img/numerosguia_29-03-2026.jpg">
              </div>
            </div>
          </div>
          <div class="col-md-4 mb-3">
            <div class="card bg-primary text-white">
              <div class="card-body">
                <h2 class="card-title">Pirámide de la Suerte</h2>
                <img alt="Piramide de la suerte 29/3/2026" src="/img/piramidedelasuerte_29-03-2026.jpg">
              </div>
            </div>
          </div>
        </div>
        """

        with NamedTemporaryFile("w", suffix=".html", encoding="utf-8") as handle:
            handle.write(html)
            handle.flush()
            call_command("scrape_cruz_daily_content", html_file=handle.name)

        rows = list(CruzDailyContent.objects.order_by("display_order"))
        self.assertEqual(len(rows), 3)
        self.assertEqual({row.draw_date for row in rows}, {date(2026, 3, 29)})
        self.assertEqual(
            [row.card_type for row in rows],
            [
                CruzDailyContent.CardType.CRUCETA,
                CruzDailyContent.CardType.GUIA,
                CruzDailyContent.CardType.PIRAMIDE,
            ],
        )
        self.assertFalse(CruzDailyContent.objects.filter(draw_date=date(2026, 3, 28)).exists())


@override_settings(CACHES=TEST_CACHES, CHANNEL_LAYERS=TEST_CHANNEL_LAYERS)
class CruzDailyContentAPITestCase(TestCase):
    def setUp(self):
        self.client_model = Client.objects.create(name="Cliente Cruz")
        self.branch = Branch.objects.create(
            client=self.client_model,
            name="Sucursal Cruz",
            is_active=True,
            paid_until=timezone.now() + timedelta(days=30),
        )
        self.device = Device.objects.create(
            device_id="tv-cruz-001",
            activation_code="CRUZ01",
            is_active=True,
            branch=self.branch,
        )
        CruzDailyContent.objects.bulk_create(
            [
                CruzDailyContent(
                    draw_date=date(2026, 3, 29),
                    card_type=CruzDailyContent.CardType.GUIA,
                    title="Guía y Probables",
                    image_url="https://example.com/guia.jpg",
                    display_order=1,
                ),
                CruzDailyContent(
                    draw_date=date(2026, 3, 29),
                    card_type=CruzDailyContent.CardType.PIRAMIDE,
                    title="Pirámide de la Suerte",
                    image_url="https://example.com/piramide.jpg",
                    display_order=2,
                ),
                CruzDailyContent(
                    draw_date=date(2026, 3, 29),
                    card_type=CruzDailyContent.CardType.CRUCETA,
                    title="Cruceta de Hoy",
                    image_url="https://example.com/cruceta.jpg",
                    display_order=0,
                ),
            ]
        )

    def test_api_returns_cards_for_valid_device_in_display_order(self):
        response = self.client.get(
            "/api/cruz-diaria/?code=CRUZ01",
            REMOTE_ADDR="10.20.30.40",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["type"] for item in payload], ["cruceta", "guia_probables", "piramide"])
        self.assertEqual({item["draw_date"] for item in payload}, {"2026-03-29"})


class PurgeScraperExecutionsCommandTestCase(TestCase):
    def test_purge_scraper_executions_keeps_recent_rows(self):
        old_started_at = timezone.make_aware(datetime(2026, 2, 1, 9, 0, 0), timezone.get_current_timezone())
        recent_started_at = timezone.now() - timedelta(days=2)

        old_execution = ScraperExecution.objects.create(
            scraper_key="lotoven_triples",
            label="Triples Lotoven",
            command_name="scrape_triples",
            draw_date=old_started_at.date(),
            status=ScraperExecution.Status.SUCCESS,
            started_at=old_started_at,
            finished_at=old_started_at + timedelta(minutes=1),
        )
        recent_execution = ScraperExecution.objects.create(
            scraper_key="condor_animalitos",
            label="Animalitos Condor",
            command_name="scrape_condor_animalitos",
            draw_date=recent_started_at.date(),
            status=ScraperExecution.Status.SUCCESS,
            started_at=recent_started_at,
            finished_at=recent_started_at + timedelta(minutes=1),
        )

        call_command("purge_scraper_executions", keep_days=14)

        self.assertFalse(ScraperExecution.objects.filter(pk=old_execution.pk).exists())
        self.assertTrue(ScraperExecution.objects.filter(pk=recent_execution.pk).exists())


@override_settings(
    CACHES=TEST_CACHES,
    CHANNEL_LAYERS=TEST_CHANNEL_LAYERS,
    SCRAPER_TELEGRAM_BOT_TOKEN="telegram-token",
    SCRAPER_TELEGRAM_CHAT_IDS=["1001"],
    SCRAPER_ADMIN_BASE_URL="http://127.0.0.1:8000",
    ADMIN_ACTIVITY_TELEGRAM_ENABLED=True,
)
class AdminActivityNotificationSignalsTestCase(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_superuser(
            username="root",
            email="root@example.com",
            password="secret123",
        )
        self.client_model = Client.objects.create(name="Cliente Ops")
        self.branch = Branch.objects.create(
            client=self.client_model,
            name="Sucursal Ops",
            is_active=True,
            paid_until=timezone.now() + timedelta(days=30),
        )
        self.device = Device.objects.create(
            device_id="tv-ops-001",
            activation_code="OPS001",
            is_active=True,
            branch=self.branch,
        )

    @patch("core.services.scraper_notification_service.requests.post")
    def test_admin_log_entry_notifies_client_creation(self, mock_post):
        content_type = ContentType.objects.get_for_model(Client)
        client_obj = Client.objects.create(name="Cliente Nuevo")

        LogEntry.objects.create(
            user=self.user,
            content_type=content_type,
            object_id=str(client_obj.pk),
            object_repr=client_obj.name,
            action_flag=ADDITION,
            change_message='[{"added": {}}]',
        )

        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args.kwargs["json"]
        self.assertIn("Actividad admin", payload["text"])
        self.assertIn("Accion: creacion", payload["text"])
        self.assertIn("Objeto: Cliente", payload["text"])

    @patch("core.services.scraper_notification_service.requests.post")
    def test_admin_log_entry_notifies_user_creation(self, mock_post):
        user_model = get_user_model()
        new_user = user_model.objects.create_user(
            username="nuevo-admin",
            email="nuevo@example.com",
            password="secret123",
        )
        content_type = ContentType.objects.get_for_model(user_model)

        LogEntry.objects.create(
            user=self.user,
            content_type=content_type,
            object_id=str(new_user.pk),
            object_repr=new_user.username,
            action_flag=ADDITION,
            change_message='[{"added": {}}]',
        )

        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args.kwargs["json"]
        self.assertIn("Accion: creacion", payload["text"])
        self.assertIn("Objeto: Usuario", payload["text"])

    @patch("core.services.scraper_notification_service.requests.post")
    def test_admin_log_entry_notifies_user_change(self, mock_post):
        user_model = get_user_model()
        target_user = user_model.objects.create_user(
            username="edit-admin",
            email="edit@example.com",
            password="secret123",
        )
        content_type = ContentType.objects.get_for_model(user_model)

        LogEntry.objects.create(
            user=self.user,
            content_type=content_type,
            object_id=str(target_user.pk),
            object_repr=target_user.username,
            action_flag=CHANGE,
            change_message='[{"changed": {"fields": ["Email address", "Staff status"]}}]',
        )

        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args.kwargs["json"]
        self.assertIn("Accion: cambio", payload["text"])
        self.assertIn("Objeto: Usuario", payload["text"])

    @patch("core.services.scraper_notification_service.requests.post")
    def test_admin_log_entry_notifies_user_deletion(self, mock_post):
        user_model = get_user_model()
        target_user = user_model.objects.create_user(
            username="delete-admin",
            email="delete@example.com",
            password="secret123",
        )
        content_type = ContentType.objects.get_for_model(user_model)

        LogEntry.objects.create(
            user=self.user,
            content_type=content_type,
            object_id=str(target_user.pk),
            object_repr=target_user.username,
            action_flag=DELETION,
            change_message="",
        )

        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args.kwargs["json"]
        self.assertIn("Accion: eliminacion", payload["text"])
        self.assertIn("Objeto: Usuario", payload["text"])

    @patch("core.services.scraper_notification_service.requests.post")
    def test_admin_log_entry_notifies_group_creation(self, mock_post):
        group = Group.objects.create(name="Operadores QA")
        content_type = ContentType.objects.get_for_model(Group)

        LogEntry.objects.create(
            user=self.user,
            content_type=content_type,
            object_id=str(group.pk),
            object_repr=group.name,
            action_flag=ADDITION,
            change_message='[{"added": {}}]',
        )

        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args.kwargs["json"]
        self.assertIn("Accion: creacion", payload["text"])
        self.assertIn("Objeto: Grupo", payload["text"])

    @patch("core.services.scraper_notification_service.requests.post")
    def test_admin_log_entry_notifies_branch_paid_until_change(self, mock_post):
        content_type = ContentType.objects.get_for_model(Branch)

        LogEntry.objects.create(
            user=self.user,
            content_type=content_type,
            object_id=str(self.branch.pk),
            object_repr=self.branch.name,
            action_flag=CHANGE,
            change_message='[{"changed": {"fields": ["Paid until"]}}]',
        )

        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args.kwargs["json"]
        self.assertIn("Accion: cambio", payload["text"])
        self.assertIn("Campos: Paid until", payload["text"])

    @patch("core.services.scraper_notification_service.requests.post")
    def test_admin_log_entry_notifies_device_deletion(self, mock_post):
        content_type = ContentType.objects.get_for_model(Device)

        LogEntry.objects.create(
            user=self.user,
            content_type=content_type,
            object_id=str(self.device.pk),
            object_repr=self.device.activation_code,
            action_flag=DELETION,
            change_message="",
        )

        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args.kwargs["json"]
        self.assertIn("Accion: eliminacion", payload["text"])
        self.assertIn("Objeto: TV", payload["text"])

    @patch("core.services.scraper_notification_service.requests.post")
    def test_login_notifies(self, mock_post):
        logged_in = self.client.login(username="root", password="secret123")

        self.assertTrue(logged_in)
        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args.kwargs["json"]
        self.assertIn("Inicio de sesion admin", payload["text"])
        self.assertIn("Usuario: root", payload["text"])

    @patch("core.services.scraper_notification_service.requests.post")
    def test_telemetry_event_notifies(self, mock_post):
        DeviceTelemetryEvent.objects.create(
            device=self.device,
            event_type=DeviceTelemetryEvent.EventType.LOAD_ERROR,
            ip_address="10.0.0.10",
            message="net::ERR_CONNECTION_TIMED_OUT",
        )

        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args.kwargs["json"]
        self.assertIn("Evento de telemetria", payload["text"])
        self.assertIn("TV: OPS001", payload["text"])
        self.assertIn("Tipo: LOAD_ERROR", payload["text"])


class ResultWindowServiceTestCase(TestCase):
    def test_delete_future_rows_for_provider_keeps_only_due_rows(self):
        provider = Provider.objects.create(
            name="Triple Chance A",
            source_url="https://example.com/provider",
            is_active=True,
        )
        draw_date = timezone.localdate()
        CurrentResult.objects.create(
            provider=provider,
            draw_date=draw_date,
            draw_time=datetime.strptime("13:00", "%H:%M").time(),
            winning_number="111",
        )
        CurrentResult.objects.create(
            provider=provider,
            draw_date=draw_date,
            draw_time=datetime.strptime("16:00", "%H:%M").time(),
            winning_number="222",
        )

        deleted = delete_future_rows_for_provider(
            model=CurrentResult,
            provider=provider,
            draw_date=draw_date,
            cutoff_time=datetime.strptime("14:00", "%H:%M").time(),
        )

        self.assertEqual(deleted, 1)
        self.assertEqual(
            list(
                CurrentResult.objects.filter(provider=provider, draw_date=draw_date)
                .values_list("winning_number", flat=True)
            ),
            ["111"],
        )


@override_settings(
    CACHES=TEST_CACHES,
    CHANNEL_LAYERS=TEST_CHANNEL_LAYERS,
    ADMIN_ACTIVITY_TELEGRAM_ENABLED=False,
    SCRAPER_TELEGRAM_BOT_TOKEN="",
    SCRAPER_TELEGRAM_CHAT_IDS=[],
)
class ClientDeletionCascadeTestCase(TestCase):
    def test_deleting_client_cascades_to_branch_devices_and_related_records(self):
        client_model = Client.objects.create(name="Cliente Baja")
        branch = Branch.objects.create(
            client=client_model,
            name="Sucursal Baja",
            is_active=True,
            paid_until=timezone.now() + timedelta(days=30),
        )
        device = Device.objects.create(
            device_id="tv-baja-001",
            activation_code="BAJA01",
            is_active=True,
            branch=branch,
        )
        DeviceTelemetrySnapshot.objects.create(device=device, last_ip_address="10.0.0.20")
        DeviceTelemetryEvent.objects.create(
            device=device,
            event_type=DeviceTelemetryEvent.EventType.LOAD_ERROR,
            ip_address="10.0.0.20",
            message="error previo a baja",
        )
        Transmission.objects.create(device=device, success=True)

        client_model.delete()

        self.assertFalse(Client.objects.filter(pk=client_model.pk).exists())
        self.assertFalse(Branch.objects.filter(pk=branch.pk).exists())
        self.assertFalse(Device.objects.filter(pk=device.pk).exists())
        self.assertFalse(DeviceTelemetrySnapshot.objects.filter(device_id=device.pk).exists())
        self.assertFalse(DeviceTelemetryEvent.objects.filter(device_id=device.pk).exists())
        self.assertFalse(Transmission.objects.filter(device_id=device.pk).exists())


class DailyRetentionCommandTestCase(TestCase):
    @patch("core.management.commands.run_daily_retention.call_command")
    def test_run_daily_retention_calls_archive_then_retention(self, mock_call_command):
        with patch("core.management.commands.run_daily_retention.timezone.localdate") as mock_localdate:
            mock_localdate.return_value = datetime(2026, 3, 20).date()

            from django.core.management import call_command

            call_command("run_daily_retention")

        self.assertEqual(
            mock_call_command.call_args_list,
            [
                call("archive_daily_triples", date="2026-03-19"),
                call("archive_daily_animalitos", date="2026-03-19"),
                call("enforce_retention", keep_archive_days=1),
            ],
        )


class PurgeTelemetryEventsCommandTestCase(TestCase):
    def setUp(self):
        self.client_model = Client.objects.create(name="Cliente QA")
        self.branch = Branch.objects.create(
            client=self.client_model,
            name="Sucursal QA",
            is_active=True,
            paid_until=timezone.now() + timedelta(days=30),
        )
        self.device = Device.objects.create(
            device_id="tv-qa-telemetry",
            activation_code="TEL123",
            is_active=True,
            branch=self.branch,
        )

    def test_purge_deletes_non_incident_events(self):
        DeviceTelemetryEvent.objects.create(
            device=self.device,
            event_type=DeviceTelemetryEvent.EventType.LOAD_ERROR,
            message="boom",
        )
        DeviceTelemetryEvent.objects.create(
            device=self.device,
            event_type=DeviceTelemetryEvent.EventType.LOAD_SUCCESS,
            message="ok",
        )

        call_command("purge_telemetry_events")

        self.assertEqual(
            list(DeviceTelemetryEvent.objects.values_list("event_type", flat=True)),
            [DeviceTelemetryEvent.EventType.LOAD_ERROR],
        )

    @override_settings(
        SCRAPER_TELEGRAM_BOT_TOKEN="telegram-token",
        SCRAPER_TELEGRAM_CHAT_IDS=["1001"],
    )
    @patch("core.services.scraper_notification_service.requests.post")
    def test_notify_active_alerts_respects_signature_cooldown(self, mock_post):
        now = timezone.now()
        monitor = ScraperHealthService.get_or_create_monitor("condor_animalitos")
        monitor.last_status = ScraperHealth.Status.FAILED
        monitor.last_started_at = now
        monitor.last_finished_at = now
        monitor.last_error_message = "condor parser failed"
        monitor.last_notified_at = now
        monitor.last_notified_signature = ScraperNotificationService.build_signature(
            {
                "scraper_key": "condor_animalitos",
                "status": "failed",
                "message": "condor parser failed",
                "last_error_message": "condor parser failed",
                "last_success_at": None,
            }
        )
        monitor.save(
            update_fields=[
                "last_status",
                "last_started_at",
                "last_finished_at",
                "last_error_message",
                "last_notified_at",
                "last_notified_signature",
                "updated_at",
            ]
        )

        sent = ScraperNotificationService.notify_active_alerts(now=now, monitors=[monitor])
        self.assertEqual(sent, 0)
        mock_post.assert_not_called()

    @override_settings(
        SCRAPER_TELEGRAM_CHAT_IDS=["1001", "1002"],
    )
    def test_get_recipients_returns_telegram_chat_ids(self):
        recipients = ScraperNotificationService.get_recipients()

        self.assertEqual(
            recipients,
            ["1001", "1002"],
        )

    @override_settings(
        SCRAPER_TELEGRAM_BOT_TOKEN="telegram-token",
        SCRAPER_TELEGRAM_CHAT_IDS=["1001"],
    )
    @patch("core.services.scraper_notification_service.requests.post")
    def test_notify_active_alerts_force_ignores_cooldown(self, mock_post):
        now = timezone.now()
        monitor = ScraperHealthService.get_or_create_monitor("condor_animalitos")
        monitor.last_status = ScraperHealth.Status.FAILED
        monitor.last_started_at = now
        monitor.last_finished_at = now
        monitor.last_error_message = "condor parser failed"
        monitor.last_notified_at = now
        monitor.last_notified_signature = ScraperNotificationService.build_signature(
            {
                "scraper_key": "condor_animalitos",
                "alert_kind": "failed_today",
                "status": "failed",
                "message": "condor parser failed",
                "last_error_message": "condor parser failed",
                "last_success_at": None,
            }
        )
        monitor.save(
            update_fields=[
                "last_status",
                "last_started_at",
                "last_finished_at",
                "last_error_message",
                "last_notified_at",
                "last_notified_signature",
                "updated_at",
            ]
        )

        sent = ScraperNotificationService.notify_active_alerts(
            now=now,
            monitors=[monitor],
            force=True,
        )

        self.assertEqual(sent, 1)
        mock_post.assert_called_once()
