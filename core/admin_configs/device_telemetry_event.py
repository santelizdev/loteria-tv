from __future__ import annotations

from django.contrib import admin

from core.models import DeviceTelemetryEvent


@admin.register(DeviceTelemetryEvent)
class DeviceTelemetryEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "event_type",
        "activation_code",
        "branch",
        "ip_address",
        "short_message",
    )
    list_filter = ("event_type", "created_at", "device__branch")
    search_fields = (
        "device__activation_code",
        "device__device_id",
        "device__branch__name",
        "ip_address",
        "message",
    )
    readonly_fields = ("device", "event_type", "ip_address", "message", "metadata", "created_at")
    autocomplete_fields = ("device",)

    def activation_code(self, obj):
        return obj.device.activation_code

    activation_code.short_description = "COD"
    activation_code.admin_order_field = "device__activation_code"

    def branch(self, obj):
        return obj.device.branch

    branch.short_description = "Sucursal"
    branch.admin_order_field = "device__branch"

    def short_message(self, obj):
        text = (obj.message or "").strip()
        if len(text) <= 80:
            return text
        return f"{text[:77]}..."

    short_message.short_description = "Mensaje"
