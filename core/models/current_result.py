from __future__ import annotations

from django.db import models
from django.utils import timezone

from .provider import Provider


class CurrentResult(models.Model):
    class ResultOrigin(models.TextChoices):
        AUTOMATIC_VALID = "automatic_valid", "Automatic valid"
        MANUAL_CONTINGENCY = "manual_contingency", "Manual contingency"

    """
    Current-day results for table-based lotteries (triples).

    `extra` is schemaless and stores provider-specific fields such as:
      - {"signo": "ARIES"}
    """

    provider = models.ForeignKey(
        Provider,
        on_delete=models.CASCADE,
        related_name="current_results",
    )

    draw_date = models.DateField(default=timezone.localdate)
    draw_time = models.TimeField()
    winning_number = models.CharField(max_length=10)
    image_url = models.URLField(blank=True)

    extra = models.JSONField(blank=True, null=True)
    result_origin = models.CharField(
        max_length=32,
        choices=ResultOrigin.choices,
        default=ResultOrigin.AUTOMATIC_VALID,
        db_index=True,
    )
    source_incident = models.ForeignKey(
        "core.ScraperIncident",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_results",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider__name", "draw_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "draw_date", "draw_time"],
                name="uniq_current_provider_draw_date_time",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider.name} {self.draw_date} {self.draw_time} {self.winning_number}"
