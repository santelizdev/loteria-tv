from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime
from unittest.mock import patch

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import CurrentResult, Provider, ScraperIncident
from core.services.scraper_execution_service import LOTOVEN_STRICT_SCHEDULE, LOTOVEN_TABLE_SIMPLE_PROVIDERS
from core.services.scraper_health_service import ScraperHealthService


class Command(BaseCommand):
    help = "Simula incidentes de scraper en local para probar deteccion, incidente y Telegram."

    def add_arguments(self, parser):
        parser.add_argument(
            "--scenario",
            choices=("technical_failure", "missing_group"),
            default="missing_group",
            help="Escenario de simulacion.",
        )
        parser.add_argument(
            "--scraper",
            default="lotoven_triples",
            help="scraper_key a simular. technical_failure soporta cualquiera; missing_group usa lotoven_triples.",
        )
        parser.add_argument(
            "--send-telegram",
            action="store_true",
            help="Permite el envio real a Telegram si la configuracion existe.",
        )
        parser.add_argument(
            "--reset-open-incidents",
            action="store_true",
            help="Elimina incidentes abiertos del scraper/fecha antes de simular para empezar limpio.",
        )

    def handle(self, *args, **options):
        scenario = options["scenario"]
        scraper_key = options["scraper"]
        send_telegram = bool(options["send_telegram"])
        reset_open_incidents = bool(options["reset_open_incidents"])

        if scenario == "missing_group" and scraper_key != "lotoven_triples":
            raise CommandError("El escenario missing_group hoy solo soporta --scraper=lotoven_triples.")

        draw_date = timezone.localdate()

        if reset_open_incidents:
            deleted, _ = ScraperIncident.objects.filter(
                scraper_key=scraper_key,
                draw_date=draw_date,
                status=ScraperIncident.Status.OPEN,
            ).delete()
            self.stdout.write(f"reset_open_incidents={deleted}")

        if scenario == "technical_failure":
            self._simulate_technical_failure(scraper_key=scraper_key, send_telegram=send_telegram)
            return

        self._simulate_missing_group(scraper_key=scraper_key, draw_date=draw_date, send_telegram=send_telegram)

    def _simulate_technical_failure(self, *, scraper_key: str, send_telegram: bool):
        with self._patch_telegram(send_telegram):
            with patch("core.services.scraper_health_service.call_command", side_effect=RuntimeError("simulated scraper failure")):
                try:
                    ScraperHealthService.run_registered(scraper_key)
                except RuntimeError as exc:
                    self.stdout.write(self.style.WARNING(f"simulated_exception={exc}"))

        incident = ScraperIncident.objects.filter(scraper_key=scraper_key).order_by("-id").first()
        if incident:
            self.stdout.write(
                self.style.SUCCESS(
                    f"incident_created id={incident.id} status={incident.status} "
                    f"reason={incident.failure_reason_code} alert_sent={incident.alert_sent}"
                )
            )

    def _simulate_missing_group(self, *, scraper_key: str, draw_date, send_telegram: bool):
        def create_partial_rows(_command_name):
            self._seed_partial_lotoven_rows(draw_date=draw_date)
            return None

        with self._patch_telegram(send_telegram):
            with patch("core.services.scraper_health_service.call_command", side_effect=create_partial_rows):
                ScraperHealthService.run_registered(scraper_key)

        incident = ScraperIncident.objects.filter(
            scraper_key=scraper_key,
            draw_date=draw_date,
        ).order_by("-id").first()
        if not incident:
            raise CommandError("No se genero incidente durante la simulacion.")

        self.stdout.write(
            self.style.SUCCESS(
                f"incident_created id={incident.id} target={incident.provider_name or '-'} "
                f"time={incident.draw_time.strftime('%H:%M') if incident.draw_time else '-'} "
                f"status={incident.status} alert_sent={incident.alert_sent}"
            )
        )
        self.stdout.write(
            "Siguiente paso: entra al admin del incidente y usa 'Carga manual controlada' para probar la resolucion."
        )

    def _seed_partial_lotoven_rows(self, *, draw_date):
        missing_group = ("Triple Chance A", "16:00")
        for provider_name in LOTOVEN_TABLE_SIMPLE_PROVIDERS:
            provider = self._get_or_create_provider(provider_name)
            CurrentResult.objects.update_or_create(
                provider=provider,
                draw_date=draw_date,
                draw_time=datetime.strptime("08:00", "%H:%M").time(),
                defaults={
                    "winning_number": "111",
                    "image_url": "",
                    "extra": None,
                    "result_origin": CurrentResult.ResultOrigin.AUTOMATIC_VALID,
                    "source_incident": None,
                },
            )

        for provider_name, times in LOTOVEN_STRICT_SCHEDULE.items():
            provider = self._get_or_create_provider(provider_name)
            for time_str in times:
                if (provider_name, time_str) == missing_group:
                    continue
                CurrentResult.objects.update_or_create(
                    provider=provider,
                    draw_date=draw_date,
                    draw_time=datetime.strptime(time_str, "%H:%M").time(),
                    defaults={
                        "winning_number": "222",
                        "image_url": "",
                        "extra": None,
                        "result_origin": CurrentResult.ResultOrigin.AUTOMATIC_VALID,
                        "source_incident": None,
                    },
                )

    @staticmethod
    def _get_or_create_provider(name: str) -> Provider:
        provider, _ = Provider.objects.get_or_create(
            name=name,
            defaults={"source_url": "https://lotoven.com", "is_active": True, "logo_url": ""},
        )
        return provider

    def _patch_telegram(self, send_telegram: bool):
        if send_telegram:
            return nullcontext()
        return patch("core.services.scraper_notification_service.requests.post", side_effect=self._fake_telegram_send)

    def _fake_telegram_send(self, *args, **kwargs):
        payload = kwargs.get("json") or {}
        chat_id = payload.get("chat_id") or "-"
        text = payload.get("text") or ""
        preview = text.splitlines()[0] if text else "-"
        self.stdout.write(f"telegram_dry_run chat_id={chat_id} preview={preview}")

        class DummyResponse:
            def raise_for_status(self):
                return None

        return DummyResponse()
