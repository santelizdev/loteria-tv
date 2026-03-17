from __future__ import annotations

from typing import Any

from django.utils import timezone

from core.models import Device, DeviceTelemetryEvent, DeviceTelemetrySnapshot


class DeviceTelemetryService:
    SNAPSHOT_ENV_FIELDS = {
        "android_version": "android_version",
        "webview_version": "webview_version",
        "device_model": "device_model",
        "app_version": "app_version",
    }

    @classmethod
    def get_or_create_snapshot(cls, *, device: Device) -> DeviceTelemetrySnapshot:
        snapshot, _ = DeviceTelemetrySnapshot.objects.get_or_create(device=device)
        return snapshot

    @classmethod
    def record_heartbeat(cls, *, device: Device, ip_address: str | None) -> DeviceTelemetrySnapshot:
        snapshot = cls.get_or_create_snapshot(device=device)
        snapshot.last_heartbeat_at = timezone.now()
        if ip_address:
            snapshot.last_ip_address = ip_address
        snapshot.save(update_fields=["last_heartbeat_at", "last_ip_address", "updated_at"])
        return snapshot

    @classmethod
    def record_event(
        cls,
        *,
        device: Device,
        event_type: str,
        ip_address: str | None,
        message: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> DeviceTelemetryEvent:
        payload = metadata or {}
        event = DeviceTelemetryEvent.objects.create(
            device=device,
            event_type=event_type,
            ip_address=ip_address or None,
            message=message or "",
            metadata=payload,
        )
        cls._update_snapshot_from_event(
            device=device,
            event_type=event_type,
            ip_address=ip_address,
            message=message,
            metadata=payload,
        )
        return event

    @classmethod
    def _update_snapshot_from_event(
        cls,
        *,
        device: Device,
        event_type: str,
        ip_address: str | None,
        message: str,
        metadata: dict[str, Any],
    ) -> DeviceTelemetrySnapshot:
        snapshot = cls.get_or_create_snapshot(device=device)
        now = timezone.now()
        update_fields = {"updated_at", "last_metadata"}

        snapshot.last_metadata = metadata or {}

        if ip_address:
            snapshot.last_ip_address = ip_address
            update_fields.add("last_ip_address")

        for payload_key, snapshot_field in cls.SNAPSHOT_ENV_FIELDS.items():
            value = str(metadata.get(payload_key) or "").strip()
            if value:
                setattr(snapshot, snapshot_field, value)
                update_fields.add(snapshot_field)

        if event_type == DeviceTelemetryEvent.EventType.LOAD_SUCCESS:
            snapshot.last_load_success_at = now
            update_fields.add("last_load_success_at")
        elif event_type == DeviceTelemetryEvent.EventType.LOAD_ERROR:
            snapshot.last_error_reported_at = now
            snapshot.last_error_reported_message = (message or "").strip()
            update_fields.update({"last_error_reported_at", "last_error_reported_message"})
        elif event_type == DeviceTelemetryEvent.EventType.LOW_MEMORY:
            snapshot.last_low_memory_at = now
            update_fields.add("last_low_memory_at")
        elif event_type == DeviceTelemetryEvent.EventType.HEARTBEAT:
            snapshot.last_heartbeat_at = now
            update_fields.add("last_heartbeat_at")

        snapshot.save(update_fields=sorted(update_fields))
        return snapshot
