from __future__ import annotations

from datetime import timedelta

from django.contrib import admin
from django.utils import timezone

from core.models import Device, DeviceTelemetryEvent
from core.services.device_telemetry_service import DeviceTelemetryService


class DeviceOnlineStatusFilter(admin.SimpleListFilter):
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
            return queryset.filter(telemetry_snapshot__last_heartbeat_at__gte=cutoff)
        return queryset.exclude(telemetry_snapshot__last_heartbeat_at__gte=cutoff)

@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "activation_code",
        "branch",
        "device_id",
        "online_status",
        "telemetry_last_ip",
        "telemetry_last_heartbeat",
        "telemetry_last_load_success",
        "telemetry_last_low_memory",
        "registered_ip",
        "is_active",
        "last_seen",
    )
    list_filter = ("is_active", "branch", DeviceOnlineStatusFilter)
    search_fields = (
        "activation_code",
        "device_id",
        "registered_ip",
        "branch__name",
        "branch__client__name",
        "telemetry_snapshot__last_ip_address",
    )
    readonly_fields = ("last_seen", "telemetry_summary", "recent_telemetry_events", "shared_ip_devices")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("branch", "telemetry_snapshot")

    def online_status(self, obj):
        snapshot = getattr(obj, "telemetry_snapshot", None)
        if not snapshot:
            return "Offline"
        return "Online" if snapshot.is_online else "Offline"

    online_status.short_description = "Estado"

    def telemetry_last_ip(self, obj):
        snapshot = getattr(obj, "telemetry_snapshot", None)
        return snapshot.last_ip_address if snapshot else ""

    telemetry_last_ip.short_description = "Ultima IP"

    def telemetry_last_heartbeat(self, obj):
        snapshot = getattr(obj, "telemetry_snapshot", None)
        return snapshot.last_heartbeat_at if snapshot else None

    telemetry_last_heartbeat.short_description = "Ultimo heartbeat"

    def telemetry_last_load_success(self, obj):
        snapshot = getattr(obj, "telemetry_snapshot", None)
        return snapshot.last_load_success_at if snapshot else None

    telemetry_last_load_success.short_description = "Ultimo exito"

    def telemetry_last_low_memory(self, obj):
        snapshot = getattr(obj, "telemetry_snapshot", None)
        return snapshot.last_low_memory_at if snapshot else None

    telemetry_last_low_memory.short_description = "Ultimo LOW_MEMORY"

    def telemetry_summary(self, obj):
        snapshot = getattr(obj, "telemetry_snapshot", None)
        if not snapshot:
            return "Sin snapshot de telemetria."
        lines = [
            f"Online: {'Si' if snapshot.is_online else 'No'}",
            f"Ultimo heartbeat: {snapshot.last_heartbeat_at or '-'}",
            f"Ultima IP: {snapshot.last_ip_address or '-'}",
            f"Ultimo LOAD_SUCCESS: {snapshot.last_load_success_at or '-'}",
            f"Ultimo error: {snapshot.last_error_reported_message or '-'}",
            f"Ultimo LOW_MEMORY: {snapshot.last_low_memory_at or '-'}",
            f"Android: {snapshot.android_version or '-'}",
            f"WebView: {snapshot.webview_version or '-'}",
            f"Modelo: {snapshot.device_model or '-'}",
            f"App: {snapshot.app_version or '-'}",
        ]
        return "\n".join(lines)

    telemetry_summary.short_description = "Resumen telemetria"

    def recent_telemetry_events(self, obj):
        events = obj.telemetry_events.filter(
            event_type__in=DeviceTelemetryService.INCIDENT_EVENT_TYPES
        )[:10]
        if not events:
            return "Sin incidentes de telemetria."
        return "\n".join(
            f"{event.created_at:%Y-%m-%d %H:%M:%S} | {event.event_type} | {event.ip_address or '-'} | {(event.message or '-').strip()}"
            for event in events
        )

    recent_telemetry_events.short_description = "Eventos recientes"

    def shared_ip_devices(self, obj):
        snapshot = getattr(obj, "telemetry_snapshot", None)
        if not snapshot or not snapshot.last_ip_address:
            return "Sin IP registrada."
        sibling_ids = (
            Device.objects.filter(telemetry_snapshot__last_ip_address=snapshot.last_ip_address)
            .exclude(pk=obj.pk)
            .values_list("activation_code", "device_id")
        )
        rows = list(sibling_ids)
        if not rows:
            return "No hay otros devices con esta IP."
        return "\n".join(f"{activation_code} | {device_id}" for activation_code, device_id in rows)

    shared_ip_devices.short_description = "Otros devices con esta IP"
