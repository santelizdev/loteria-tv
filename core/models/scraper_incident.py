from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class ScraperIncident(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESOLVED = "resolved", "Resolved"

    class ContingencyStage(models.TextChoices):
        OBSERVING = "observing", "Observing"
        FALLBACK_ACTIVE = "fallback_active", "Fallback active"
        MANUAL_REQUIRED = "manual_required", "Manual required"

    fingerprint = models.CharField(max_length=255, unique=True)
    scraper_key = models.CharField(max_length=64, db_index=True)
    label = models.CharField(max_length=120)
    command_name = models.CharField(max_length=120)
    draw_date = models.DateField(default=timezone.localdate, db_index=True)
    provider_name = models.CharField(max_length=120, blank=True, default="")
    draw_time = models.TimeField(null=True, blank=True)
    result_model = models.CharField(max_length=64, blank=True, default="")
    detection_scope = models.CharField(max_length=16, blank=True, default="")
    validation_profile = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    severity = models.CharField(max_length=16, blank=True, default="critical")
    failure_reason_code = models.CharField(max_length=64, blank=True, default="")
    summary = models.TextField(blank=True, default="")
    evidence_summary = models.TextField(blank=True, default="")
    contingency_stage = models.CharField(
        max_length=24,
        choices=ContingencyStage.choices,
        default=ContingencyStage.OBSERVING,
        db_index=True,
    )
    primary_attempt_count = models.PositiveIntegerField(default=1)
    fallback_attempt_count = models.PositiveIntegerField(default=0)
    fallback_scraper_key = models.CharField(max_length=64, blank=True, default="")
    fallback_activated_at = models.DateTimeField(null=True, blank=True)
    manual_enabled_at = models.DateTimeField(null=True, blank=True)
    alert_sent = models.BooleanField(default=False)
    alert_sent_at = models.DateTimeField(null=True, blank=True)
    occurrence_count = models.PositiveIntegerField(default=1)
    first_detected_at = models.DateTimeField(default=timezone.now)
    last_detected_at = models.DateTimeField(default=timezone.now)
    last_execution = models.ForeignKey(
        "core.ScraperExecution",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incidents",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="resolved_scraper_incidents",
    )
    resolution_note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["status", "-last_detected_at", "scraper_key", "provider_name"]
        indexes = [
            models.Index(fields=["scraper_key", "draw_date", "status"]),
            models.Index(fields=["provider_name", "draw_date", "status"]),
            models.Index(fields=["status", "contingency_stage"]),
        ]
        verbose_name = "Scraper incident"
        verbose_name_plural = "Scraper incidents"

    def __str__(self) -> str:
        target = self.provider_name or self.scraper_key
        return f"{self.label} {self.draw_date} {target} [{self.status}]"
