# core/models/provider.py
from django.db import models


class Provider(models.Model):
    name = models.CharField(max_length=100)
    source_url = models.URLField()
    is_active = models.BooleanField(default=True)
    logo_url = models.URLField(blank=True, null=True)   

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
