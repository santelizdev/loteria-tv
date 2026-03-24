from __future__ import annotations

from django.db import models
from django.utils import timezone


class ScraperExecution(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        INCIDENT = "incident", "Incident"

    scraper_key = models.CharField(max_length=64, db_index=True)
    label = models.CharField(max_length=120)
    command_name = models.CharField(max_length=120)
    draw_date = models.DateField(default=timezone.localdate, db_index=True)
    validation_profile = models.CharField(max_length=32, blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField(default=timezone.now, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    provider_scope = models.JSONField(blank=True, default=list)
    expected_groups = models.JSONField(blank=True, default=list)
    persisted_groups = models.JSONField(blank=True, default=list)
    missing_groups = models.JSONField(blank=True, default=list)

    failure_reason_code = models.CharField(max_length=64, blank=True, default="")
    evidence_summary = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    incident_detected = models.BooleanField(default=False)
    incident_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-started_at", "scraper_key"]
        indexes = [
            models.Index(fields=["scraper_key", "draw_date"]),
            models.Index(fields=["status", "draw_date"]),
        ]
        verbose_name = "Scraper execution"
        verbose_name_plural = "Scraper executions"

    def __str__(self) -> str:
        return f"{self.label} {self.draw_date} [{self.status}]"
