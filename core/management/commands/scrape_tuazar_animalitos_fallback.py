from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import ScraperIncident
from core.services.tuazar_animalito_fallback_service import TuAzarAnimalitoFallbackService


class Command(BaseCommand):
    help = "Scraper de emergencia para Lotto Rey desde TuAzar animalitos."

    def add_arguments(self, parser):
        parser.add_argument("--date", type=str, default=None, help="Fecha objetivo YYYY-MM-DD. Solo HOY.")
        parser.add_argument("--incident-id", type=int, default=None, help="Incidente a vincular como source_incident.")

    def handle(self, *args, **options):
        target_date = self._parse_date(options.get("date"))
        incident = self._get_incident(options.get("incident_id"))

        result = TuAzarAnimalitoFallbackService.run_lottorey(
            target_date=target_date,
            incident=incident,
        )
        if not result.success:
            raise CommandError(result.detail or "Fallback sin filas utilizables.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Fallback OK {result.provider_name}: filas={result.rows_persisted}"
            )
        )

    def _parse_date(self, raw: str | None):
        if not raw:
            return timezone.localdate()
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError as exc:
            raise CommandError("Fecha invalida. Usa YYYY-MM-DD.") from exc

    def _get_incident(self, incident_id: int | None) -> ScraperIncident | None:
        if not incident_id:
            return None
        try:
            return ScraperIncident.objects.get(pk=incident_id)
        except ScraperIncident.DoesNotExist as exc:
            raise CommandError(f"No existe ScraperIncident id={incident_id}.") from exc
