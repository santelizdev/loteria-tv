# core/admin.py
from django.contrib import admin
from .models import AnimalitoArchive

from .admin_configs import (  # noqa: F401
    client,
    branch,
    device,
    device_telemetry_snapshot,
    device_telemetry_event,
    provider,
    current_result,
    result_archive,
    transmission,
    animalito_result,
    scraper_health,
)

@admin.register(AnimalitoArchive)
class AnimalitoArchiveAdmin(admin.ModelAdmin):
    def get_list_display(self, request):
        return [f.name for f in self.model._meta.fields]

    def get_list_filter(self, request):
        fields = {f.name for f in self.model._meta.fields}
        return tuple([f for f in ("provider", "draw_date") if f in fields])
