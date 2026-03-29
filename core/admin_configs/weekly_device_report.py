from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib import admin
from django.template.response import TemplateResponse
from django.utils import timezone

from core.models import Device, WeeklyDeviceReport


@dataclass(frozen=True)
class WeeklyDeviceLine:
    activation_code: str
    device_id: str
    last_seen: object
    last_heartbeat_at: object
    branch_name: str
    client_name: str


@admin.register(WeeklyDeviceReport)
class WeeklyDeviceReportAdmin(admin.ModelAdmin):
    change_list_template = "admin/core/weekly_device_report/change_list.html"

    def get_queryset(self, request):
        return Device.objects.none()

    def has_module_permission(self, request):
        return bool(request.user and request.user.is_active and request.user.is_staff)

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        active_devices = list(
            Device.objects.select_related("branch__client", "telemetry_snapshot")
            .filter(
                is_active=True,
                branch__isnull=False,
                branch__is_active=True,
                branch__paid_until__gte=timezone.now(),
            )
            .order_by("branch__client__name", "branch__name", "activation_code")
        )
        weekly_rate = self._get_weekly_rate()
        report_rows = self._build_report_rows(active_devices=active_devices, weekly_rate=weekly_rate)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Resumen semanal por pantallas activas",
            "report_rows": report_rows,
            "summary": self._build_summary(report_rows=report_rows, weekly_rate=weekly_rate),
            "generated_at": timezone.localtime(),
            "weekly_rate": weekly_rate,
        }
        if extra_context:
            context.update(extra_context)
        return TemplateResponse(request, self.change_list_template, context)

    @staticmethod
    def _get_weekly_rate() -> Decimal:
        raw_value = getattr(settings, "WEEKLY_DEVICE_RATE_USD", "3")
        try:
            return Decimal(str(raw_value))
        except Exception:
            return Decimal("3")

    def _build_report_rows(
        self,
        *,
        active_devices: list[Device],
        weekly_rate: Decimal,
    ) -> list[dict[str, Any]]:
        grouped: OrderedDict[int, dict[str, Any]] = OrderedDict()

        for device in active_devices:
            branch = device.branch
            client = branch.client
            client_bucket = grouped.setdefault(
                client.pk,
                {
                    "client_id": client.pk,
                    "client_name": client.name,
                    "membership_groups": OrderedDict(),
                    "device_count": 0,
                },
            )
            membership_key = (
                branch.membership_started_at.isoformat() if branch.membership_started_at else "",
                branch.paid_until.isoformat() if branch.paid_until else "",
            )
            membership_bucket = client_bucket["membership_groups"].setdefault(
                membership_key,
                {
                    "membership_started_at": branch.membership_started_at,
                    "membership_ends_at": branch.paid_until,
                    "branches": OrderedDict(),
                    "device_count": 0,
                    "weekly_total_usd": Decimal("0"),
                },
            )
            branch_bucket = membership_bucket["branches"].setdefault(
                branch.pk,
                {
                    "branch_id": branch.pk,
                    "branch_name": branch.name,
                    "devices": [],
                    "device_count": 0,
                },
            )
            snapshot = getattr(device, "telemetry_snapshot", None)
            branch_bucket["devices"].append(
                WeeklyDeviceLine(
                    activation_code=device.activation_code,
                    device_id=device.device_id,
                    last_seen=device.last_seen,
                    last_heartbeat_at=getattr(snapshot, "last_heartbeat_at", None),
                    branch_name=branch.name,
                    client_name=client.name,
                )
            )
            branch_bucket["device_count"] += 1
            membership_bucket["device_count"] += 1
            membership_bucket["weekly_total_usd"] = weekly_rate * membership_bucket["device_count"]
            client_bucket["device_count"] += 1

        rows: list[dict[str, Any]] = []
        for client_bucket in grouped.values():
            membership_groups = []
            branch_count = 0
            for membership_bucket in client_bucket["membership_groups"].values():
                branches = list(membership_bucket["branches"].values())
                branch_count += len(branches)
                membership_groups.append(
                    {
                        "membership_started_at": membership_bucket["membership_started_at"],
                        "membership_ends_at": membership_bucket["membership_ends_at"],
                        "branches": branches,
                        "branch_count": len(branches),
                        "device_count": membership_bucket["device_count"],
                        "weekly_total_usd": membership_bucket["weekly_total_usd"],
                    }
                )
            rows.append(
                {
                    "client_id": client_bucket["client_id"],
                    "client_name": client_bucket["client_name"],
                    "membership_groups": membership_groups,
                    "branch_count": branch_count,
                    "device_count": client_bucket["device_count"],
                    "weekly_total_usd": weekly_rate * client_bucket["device_count"],
                }
            )
        return rows

    @staticmethod
    def _build_summary(*, report_rows: list[dict[str, Any]], weekly_rate: Decimal) -> dict[str, Any]:
        client_count = len(report_rows)
        branch_count = sum(row["branch_count"] for row in report_rows)
        device_count = sum(row["device_count"] for row in report_rows)
        return {
            "client_count": client_count,
            "branch_count": branch_count,
            "device_count": device_count,
            "weekly_total_usd": weekly_rate * device_count,
        }
