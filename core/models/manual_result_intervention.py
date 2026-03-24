from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from .provider import Provider


class ManualResultIntervention(models.Model):
    class ResultModel(models.TextChoices):
        CURRENT_RESULT = "CurrentResult", "CurrentResult"
        ANIMALITO_RESULT = "AnimalitoResult", "AnimalitoResult"

    class ActionType(models.TextChoices):
        CREATE = "create", "Create"
        REPLACE = "replace", "Replace"

    incident = models.ForeignKey(
        "core.ScraperIncident",
        on_delete=models.CASCADE,
        related_name="manual_interventions",
    )
    result_model = models.CharField(max_length=32, choices=ResultModel.choices)
    action_type = models.CharField(max_length=16, choices=ActionType.choices)
    provider = models.ForeignKey(
        Provider,
        on_delete=models.CASCADE,
        related_name="manual_interventions",
    )
    draw_date = models.DateField()
    draw_time = models.TimeField()
    previous_snapshot = models.JSONField(blank=True, default=dict)
    new_snapshot = models.JSONField(blank=True, default=dict)
    note = models.TextField(blank=True, default="")
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="manual_result_interventions",
    )
    performed_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-performed_at", "-id"]
        verbose_name = "Manual result intervention"
        verbose_name_plural = "Manual result interventions"

    def __str__(self) -> str:
        return (
            f"{self.result_model} {self.provider.name} {self.draw_date} "
            f"{self.draw_time} [{self.action_type}]"
        )
