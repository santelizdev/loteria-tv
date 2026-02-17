from django.db import models
from django.utils import timezone
from .provider import Provider

class AnimalitoArchive(models.Model):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name="archived_animalitos")
    draw_date = models.DateField(default=timezone.localdate)
    draw_time = models.TimeField()
    animal_number = models.CharField(max_length=2)
    animal_name = models.CharField(max_length=50)
    animal_image_url = models.URLField()
    provider_logo_url = models.URLField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["provider__name", "draw_date", "draw_time"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "draw_date", "draw_time"], name="uniq_animalito_archive_provider_date_time")
        ]
