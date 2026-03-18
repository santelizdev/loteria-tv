from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Branch, Client, Device, DeviceTelemetryEvent, ScraperHealth
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

@override_settings(CACHES=TEST_CACHES, CHANNEL_LAYERS=TEST_CHANNEL_LAYERS)
class ScraperHealthServiceTestCase(TestCase):
    @patch("core.services.scraper_health_service.call_command")
    def test_run_registered_success_marks_monitor(self, mock_call_command):
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
        monitor.save(
            update_fields=[
                "last_status",
                "last_started_at",
                "last_finished_at",
                "last_error_message",
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


class ScraperNotificationServiceTestCase(TestCase):
    @override_settings(SCRAPER_ALERT_EMAILS=["ops@example.com"], DEFAULT_FROM_EMAIL="noreply@example.com")
    @patch("core.services.scraper_notification_service.send_mail")
    def test_notify_active_alerts_sends_email_and_marks_monitor(self, mock_send_mail):
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

        sent = ScraperNotificationService.notify_active_alerts(now=now)

        self.assertEqual(sent, 1)
        mock_send_mail.assert_called_once()
        monitor.refresh_from_db()
        self.assertIsNotNone(monitor.last_notified_at)
        self.assertTrue(monitor.last_notified_signature)

    @override_settings(SCRAPER_ALERT_EMAILS=["ops@example.com"], DEFAULT_FROM_EMAIL="noreply@example.com")
    @patch("core.services.scraper_notification_service.send_mail")
    def test_notify_active_alerts_respects_signature_cooldown(self, mock_send_mail):
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

        sent = ScraperNotificationService.notify_active_alerts(now=now)
        self.assertEqual(sent, 0)
        mock_send_mail.assert_not_called()

    @override_settings(
        SCRAPER_ALERT_EMAILS=["ops@example.com"],
        SCRAPER_ALERT_GROUPS=["Operators"],
        SCRAPER_ALERT_USERNAMES=["alice"],
    )
    def test_get_recipients_combines_env_users_and_groups(self):
        operators = Group.objects.create(name="Operators")
        user_model = get_user_model()
        group_user = user_model.objects.create_user(
            username="group-user",
            email="group@example.com",
            password="secret",
        )
        group_user.groups.add(operators)
        named_user = user_model.objects.create_user(
            username="alice",
            email="alice@example.com",
            password="secret",
        )

        recipients = ScraperNotificationService.get_recipients()

        self.assertEqual(
            recipients,
            ["alice@example.com", "group@example.com", "ops@example.com"],
        )

    @override_settings(SCRAPER_ALERT_EMAILS=["ops@example.com"], DEFAULT_FROM_EMAIL="noreply@example.com")
    @patch("core.services.scraper_notification_service.send_mail")
    def test_notify_active_alerts_force_ignores_cooldown(self, mock_send_mail):
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
        mock_send_mail.assert_called_once()
