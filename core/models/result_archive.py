from django.db import models
from django.utils import timezone
from .provider import Provider

class ResultArchive(models.Model):
    provider = models.ForeignKey(
        Provider,
        on_delete=models.CASCADE,
        related_name="archived_results",  # 👈 distinto al current
    )

    draw_date = models.DateField(default=timezone.localdate)
    draw_time = models.TimeField()
    winning_number = models.CharField(max_length=10)
    image_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["provider__name", "draw_date", "draw_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "draw_date", "draw_time"],
                name="uniq_archive_provider_draw_date_time",  # 👈 nombre único
            ),
        ]

    def __str__(self):
        return f"[ARCHIVE] {self.provider.name} {self.draw_date} - {self.winning_number}"
