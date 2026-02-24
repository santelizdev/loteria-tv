# core/admin.py
from django.contrib import admin
from .admin_configs import (  # noqa: F401
    client,
    branch,
    device,
    provider,
    current_result,
    result_archive,
    transmission,
    animalito_result,
)
from .models import Device
@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "branch",
        "device_id",
        "activation_code",   # ✅ nueva columna
        "registered_ip",
        "is_active",
        "last_seen",
    )
    search_fields = ("device_id", "activation_code", "registered_ip", "branch__name")
    list_filter = ("is_active", "branch")