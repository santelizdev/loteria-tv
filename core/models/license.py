# core/models/license.py
from django.db import models
from django.utils import timezone


class License(models.Model):
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({'ACTIVA' if self.is_active else 'INACTIVA'})"
