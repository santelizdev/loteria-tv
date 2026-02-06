from django.contrib import admin
from core.models import Device

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ("id", "branch", "device_id", "registered_ip", "is_active", "last_seen")
    list_filter = ("is_active",)
    search_fields = ("device_id", "branch__client__name")
    readonly_fields = ("last_seen",)
