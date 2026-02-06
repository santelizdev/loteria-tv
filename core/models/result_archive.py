from django.db import models

class ResultArchive(models.Model):
    provider = models.ForeignKey("Provider", on_delete=models.CASCADE)
    variant = models.CharField(max_length=50)  # "triple" | "animalito"
    draw_date = models.DateField()
    draw_time = models.TimeField()
    number = models.CharField(max_length=10)
    zodiac = models.CharField(max_length=10, blank=True, null=True)

    extra = models.JSONField(blank=True, null=True)  # ✅ nuevo

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["draw_date", "provider"]),
            models.Index(fields=["variant", "draw_date"]),
        ]

    def __str__(self):
        return f"{self.provider} {self.draw_date} {self.draw_time}"
