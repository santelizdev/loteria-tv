from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.services.scraper_health_service import ScraperHealthService
from core.services.scraper_notification_service import ScraperNotificationService


class Command(BaseCommand):
    help = "Envía notificaciones internas por Telegram para incidentes y alertas activas de scrapers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra las alertas/destinatarios que se notificarian sin enviar Telegram.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Ignora el cooldown y fuerza el envio para alertas activas.",
        )
        parser.add_argument(
            "--scraper",
            action="append",
            dest="scrapers",
            default=[],
            help="Limita el envio a un scraper_key especifico. Puede repetirse.",
        )

    def handle(self, *args, **options):
        scraper_keys = options["scrapers"] or []
        force = bool(options["force"])
        dry_run = bool(options["dry_run"])

        monitors = None
        if scraper_keys:
            try:
                monitors = [
                    ScraperHealthService.get_or_create_monitor(scraper_key)
                    for scraper_key in scraper_keys
                ]
            except KeyError as exc:
                raise CommandError(str(exc)) from exc

        if dry_run:
            recipients = ScraperNotificationService.get_recipients()
            health_decisions = ScraperNotificationService.collect_pending_notifications(
                monitors=monitors,
                force=force,
            )
            incident_decisions = ScraperNotificationService.collect_pending_incident_notifications(
                force=force,
            )
            self.stdout.write(f"telegram_chat_ids={', '.join(recipients) if recipients else '-'}")
            self.stdout.write(f"pending_health_notifications={len(health_decisions)}")
            self.stdout.write(f"pending_incident_notifications={len(incident_decisions)}")
            for decision in health_decisions:
                alert = decision.alert
                self.stdout.write(
                    f"- health {alert['scraper_key']} [{alert['alert_kind']}] {alert['message']}"
                )
            for decision in incident_decisions:
                incident = decision.incident
                self.stdout.write(
                    f"- incident #{incident.id} {incident.scraper_key} "
                    f"{incident.provider_name or '-'} {incident.failure_reason_code}"
                )
            return

        health_sent = ScraperNotificationService.notify_active_alerts(monitors=monitors, force=force)
        incident_sent = ScraperNotificationService.notify_pending_incidents(force=force)
        self.stdout.write(
            self.style.SUCCESS(
                f"Scraper notifications sent health={health_sent} incident={incident_sent}"
            )
        )
