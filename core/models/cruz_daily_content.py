from __future__ import annotations

from django.db import models
from django.utils import timezone


class CruzDailyContent(models.Model):
    class CardType(models.TextChoices):
        CRUCETA = "cruceta", "Cruceta de Hoy"
        GUIA = "guia_probables", "Guia y Probables"
        PIRAMIDE = "piramide", "Piramide de la Suerte"

    draw_date = models.DateField(default=timezone.localdate, db_index=True)
    card_type = models.CharField(max_length=32, choices=CardType.choices)
    title = models.CharField(max_length=120)
    image_url = models.URLField()
    image_alt = models.CharField(max_length=255, blank=True, default="")
    display_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["draw_date", "card_type"],
                name="uniq_cruz_daily_content_draw_date_card_type",
            ),
        ]
        verbose_name = "Cruz diaria"
        verbose_name_plural = "Cruces diarias"

    def __str__(self) -> str:
        return f"{self.draw_date} {self.title}"
