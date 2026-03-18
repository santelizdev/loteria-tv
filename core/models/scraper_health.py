from __future__ import annotations

from django.db import models


class ScraperHealth(models.Model):
    class Status(models.TextChoices):
        NEVER = "never", "Never"
        RUNNING = "running", "Running"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    scraper_key = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=120)
    command_name = models.CharField(max_length=120)
    last_status = models.CharField(max_length=16, choices=Status.choices, default=Status.NEVER)
    last_started_at = models.DateTimeField(null=True, blank=True)
    last_finished_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(blank=True, default="")
    last_error_traceback = models.TextField(blank=True, default="")
    consecutive_failures = models.PositiveIntegerField(default=0)
    last_notified_at = models.DateTimeField(null=True, blank=True)
    last_notified_signature = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["label"]
        verbose_name = "Scraper health"
        verbose_name_plural = "Scraper health"

    def __str__(self) -> str:
        return f"{self.label} [{self.last_status}]"
