from django.db import models
from .provider import Provider


class AnimalitoResult(models.Model):
    """
    Guarda resultados de animalitos por proveedor y horario.
    - Normalización: Provider es FK (evita duplicar strings)
    - Restricción única: (provider, draw_date, draw_time) evita duplicados
    """

    provider = models.ForeignKey(
        Provider,
        on_delete=models.CASCADE,
        related_name="animalito_results",
    )

    # Fecha del sorteo (la página permite filtrar por fecha)
    draw_date = models.DateField()

    # Hora del sorteo (ej: 08:00 AM)
    draw_time = models.TimeField()

    # Número del animalito (0..99). Guardamos como entero, ligero en sqlite.
    animal_number = models.CharField(max_length=2)

    # Nombre del animalito ("Ardilla", "Pavo Real", etc.)
    animal_name = models.CharField(max_length=50)

    # URLs (guardamos url completa normalizada)
    animal_image_url = models.URLField()
    provider_logo_url = models.URLField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["provider__name", "draw_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "draw_date", "draw_time"],
                name="uniq_provider_animalito_draw",
            )
        ]

    def __str__(self):
        return f"{self.provider.name} {self.draw_date} {self.draw_time} -> {self.animal_number} {self.animal_name}"
