from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.services.scraper_health_service import ScraperHealthService
from core.services.scraper_notification_service import ScraperNotificationService


class Command(BaseCommand):
    help = "Ejecuta el set de scrapers registrados usando el monitor interno de salud."

    def add_arguments(self, parser):
        parser.add_argument(
            "--scraper",
            action="append",
            dest="scrapers",
            default=[],
            help="Limita la corrida a un scraper_key especifico. Puede repetirse.",
        )
        parser.add_argument(
            "--notify",
            action="store_true",
            help="Evalua y dispara notificaciones internas al finalizar.",
        )
        parser.add_argument(
            "--ignore-errors",
            action="store_true",
            help="No retorna exit code 1 aunque algun scraper falle.",
        )

    def handle(self, *args, **options):
        selected_keys = options["scrapers"] or list(ScraperHealthService.REGISTRY.keys())
        notify = bool(options["notify"])
        ignore_errors = bool(options["ignore_errors"])

        failures: list[str] = []

        for scraper_key in selected_keys:
            try:
                definition = ScraperHealthService.get_definition(scraper_key)
            except KeyError as exc:
                raise CommandError(str(exc)) from exc

            self.stdout.write(f"Running {definition.key} ({definition.command_name})...")
            try:
                ScraperHealthService.run_registered(definition.key)
            except Exception as exc:
                failures.append(f"{definition.key}: {exc}")
                self.stderr.write(self.style.ERROR(f"FAIL {definition.key}: {exc}"))
                continue

            self.stdout.write(self.style.SUCCESS(f"OK {definition.key}"))

        if notify:
            sent = ScraperNotificationService.notify_active_alerts()
            self.stdout.write(f"internal_notifications_sent={sent}")

        if failures and not ignore_errors:
            raise CommandError(" ; ".join(failures))
