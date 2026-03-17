from __future__ import annotations

from datetime import timedelta

from django.db import models
from django.utils import timezone

from core.services.device_redis_service import DeviceRedisService


class DeviceTelemetrySnapshot(models.Model):
    device = models.OneToOneField(
        "Device",
        on_delete=models.CASCADE,
        related_name="telemetry_snapshot",
    )
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    last_ip_address = models.GenericIPAddressField(null=True, blank=True)
    last_load_success_at = models.DateTimeField(null=True, blank=True)
    last_error_reported_at = models.DateTimeField(null=True, blank=True)
    last_error_reported_message = models.TextField(blank=True, default="")
    last_low_memory_at = models.DateTimeField(null=True, blank=True)
    android_version = models.CharField(max_length=64, blank=True, default="")
    webview_version = models.CharField(max_length=128, blank=True, default="")
    device_model = models.CharField(max_length=128, blank=True, default="")
    app_version = models.CharField(max_length=64, blank=True, default="")
    last_metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["device__activation_code"]
        verbose_name = "Device telemetry snapshot"
        verbose_name_plural = "Device telemetry snapshots"

    def __str__(self) -> str:
        return f"{self.device.activation_code} telemetry"

    @property
    def is_online(self) -> bool:
        if not self.last_heartbeat_at:
            return False
        cutoff = timezone.now() - timedelta(seconds=DeviceRedisService.TTL_SECONDS)
        return self.last_heartbeat_at >= cutoff
