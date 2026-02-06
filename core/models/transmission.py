# core/models/transmission.py
from django.db import models
from .device import Device


class Transmission(models.Model):
    device = models.ForeignKey(
        Device,
        on_delete=models.CASCADE,
        related_name="transmissions",
    )

    success = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

   # class Meta:
    #    ordering = ["-created_at"]
