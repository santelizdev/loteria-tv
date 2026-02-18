from django.db import models


class Client(models.Model):
    name = models.CharField(max_length=150)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    
    logo = models.ImageField(upload_to="clients/logos/", null=True, blank=True)
    
    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
