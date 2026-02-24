# core/admin.py

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
from django.contrib import admin
from .models import Device

class DeviceAdmin(admin.ModelAdmin):
    list_display = ("id","branch","device_id","activation_code","registered_ip","is_active","last_seen")

admin.site.register(Device, DeviceAdmin)