from django.db import models
from django.utils import timezone
from .provider import Provider

class CurrentResult(models.Model):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="current_results")

    draw_date = models.DateField(default=timezone.localdate)  # ✅ nuevo
    draw_time = models.TimeField()
    winning_number = models.CharField(max_length=10)
    image_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["provider__name", "draw_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "draw_date", "draw_time"],  # ✅ incluye draw_date
                name="uniq_current_provider_draw_date_time"
            ),
        ]

    def __str__(self):
        return f"{self.provider.name} {self.draw_date} - {self.winning_number}"
