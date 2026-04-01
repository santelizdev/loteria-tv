from __future__ import annotations

from django.core.management.base import BaseCommand

from core.services.scraper_execution_retention_service import ScraperExecutionRetentionService


class Command(BaseCommand):
    help = "Elimina historico de ScraperExecution y conserva solo hoy/ayer por defecto."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-days",
            type=int,
            default=2,
            help="Cantidad de dias a conservar contando hoy. Default: 2",
        )

    def handle(self, *args, **options):
        deleted = ScraperExecutionRetentionService.prune_old_executions(
            keep_days=options["keep_days"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"ScraperExecution podados: {deleted}"
            )
        )
