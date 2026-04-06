from django.core.validators import MinValueValidator
from django.db import models


class DisplaySettings(models.Model):
    rotation_seconds = models.PositiveIntegerField(
        default=40,
        validators=[MinValueValidator(1)],
        help_text="Duracion general de rotacion para tablas en la TV, expresada en segundos.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuracion de pantalla TV"
        verbose_name_plural = "Configuracion de pantalla TV"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"rotation_seconds": 40})
        return obj

    def __str__(self):
        return f"Rotacion TV: {self.rotation_seconds}s"
