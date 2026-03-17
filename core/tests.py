from __future__ import annotations

from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Branch, Client, Device, DeviceTelemetryEvent


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
