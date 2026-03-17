from __future__ import annotations

from datetime import timedelta

from django.contrib import admin
from django.utils import timezone

from core.models import DeviceTelemetrySnapshot


class OnlineStatusFilter(admin.SimpleListFilter):
    title = "online"
    parameter_name = "online_state"

    def lookups(self, request, model_admin):
        return (
            ("online", "Online"),
            ("offline", "Offline"),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value not in {"online", "offline"}:
            return queryset
        cutoff = timezone.now() - timedelta(seconds=90)
        if value == "online":
            return queryset.filter(last_heartbeat_at__gte=cutoff)
        return queryset.filter(last_heartbeat_at__lt=cutoff) | queryset.filter(last_heartbeat_at__isnull=True)


@admin.register(DeviceTelemetrySnapshot)
class DeviceTelemetrySnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "activation_code",
        "branch",
        "online_status",
        "last_heartbeat_at",
        "last_ip_address",
        "last_load_success_at",
        "last_low_memory_at",
        "android_version",
        "webview_version",
    )
    list_filter = (OnlineStatusFilter, "device__branch")
    search_fields = (
        "device__activation_code",
        "device__device_id",
        "device__branch__name",
        "last_ip_address",
        "device_model",
        "webview_version",
    )
    readonly_fields = (
        "device",
        "last_heartbeat_at",
        "last_ip_address",
        "last_load_success_at",
        "last_error_reported_at",
        "last_error_reported_message",
        "last_low_memory_at",
        "android_version",
        "webview_version",
        "device_model",
        "app_version",
        "last_metadata",
        "related_devices_on_same_ip",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("device",)

    def activation_code(self, obj):
        return obj.device.activation_code

    activation_code.short_description = "COD"
    activation_code.admin_order_field = "device__activation_code"

    def branch(self, obj):
        return obj.device.branch

    branch.short_description = "Sucursal"
    branch.admin_order_field = "device__branch"

    def online_status(self, obj):
        return "Online" if obj.is_online else "Offline"

    online_status.short_description = "Estado"

    def related_devices_on_same_ip(self, obj):
        if not obj.last_ip_address:
            return "Sin IP registrada."
        siblings = (
            DeviceTelemetrySnapshot.objects.select_related("device", "device__branch")
            .filter(last_ip_address=obj.last_ip_address)
            .exclude(pk=obj.pk)
            .order_by("device__activation_code")
        )
        if not siblings.exists():
            return "No hay otros devices vistos con esta IP."
        return "\n".join(
            f"{item.device.activation_code} | {item.device.device_id} | {item.device.branch or 'Sin sucursal'}"
            for item in siblings
        )

    related_devices_on_same_ip.short_description = "Otros devices con esta IP"
