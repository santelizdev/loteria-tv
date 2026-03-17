from __future__ import annotations

from django.db import models


class DeviceTelemetryEvent(models.Model):
    class EventType(models.TextChoices):
        HEARTBEAT = "HEARTBEAT", "Heartbeat"
        LOAD_SUCCESS = "LOAD_SUCCESS", "Load success"
        LOAD_ERROR = "LOAD_ERROR", "Load error"
        LOW_MEMORY = "LOW_MEMORY", "Low memory"
        APP_START = "APP_START", "App start"
        APP_RESUME = "APP_RESUME", "App resume"
        APP_PAUSE = "APP_PAUSE", "App pause"
        APP_STOP = "APP_STOP", "App stop"
        WEBVIEW_INFO = "WEBVIEW_INFO", "WebView info"
        CUSTOM = "CUSTOM", "Custom"

    device = models.ForeignKey(
        "Device",
        on_delete=models.CASCADE,
        related_name="telemetry_events",
    )
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    message = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["ip_address", "created_at"]),
        ]
        verbose_name = "Device telemetry event"
        verbose_name_plural = "Device telemetry events"

    def __str__(self) -> str:
        return f"{self.device.activation_code} {self.event_type} {self.created_at:%Y-%m-%d %H:%M:%S}"
