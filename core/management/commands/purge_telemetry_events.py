from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from core.models import DeviceTelemetryEvent
from core.services.device_telemetry_service import DeviceTelemetryService


class Command(BaseCommand):
    help = (
        "Purga ruido de telemetry events: elimina eventos no incidentes y, opcionalmente, "
        "incidentes muy antiguos."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Solo muestra conteos, no borra.")
        parser.add_argument(
            "--keep-incident-days",
            type=int,
            default=30,
            help="Mantiene incidentes recientes por N dias (default: 30).",
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        keep_days = int(options["keep_incident_days"])
        cutoff = timezone.now() - timedelta(days=keep_days)

        incident_q = DeviceTelemetryService.incident_events_q()
        info_qs = DeviceTelemetryEvent.objects.exclude(incident_q)
        stale_incident_qs = DeviceTelemetryEvent.objects.filter(incident_q, created_at__lt=cutoff)

        self.stdout.write(
            f"incident_types={sorted(DeviceTelemetryService.INCIDENT_EVENT_TYPES)} "
            f"custom_severities={sorted(DeviceTelemetryService.INCIDENT_SEVERITIES)}"
        )
        self.stdout.write(f"keep_incident_days={keep_days} cutoff={cutoff.isoformat()}")
        self.stdout.write(f"non_incident_events={info_qs.count()}")
        self.stdout.write(f"stale_incident_events={stale_incident_qs.count()}")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run: no changes applied."))
            return

        deleted_info, _ = info_qs.delete()
        deleted_stale, _ = stale_incident_qs.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Purga completada: non_incident_deleted={deleted_info} stale_incident_deleted={deleted_stale}"
            )
        )
