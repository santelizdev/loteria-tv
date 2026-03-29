from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import ScraperExecution


class Command(BaseCommand):
    help = "Purge old ScraperExecution rows to keep ops tables lightweight."

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-days",
            type=int,
            default=int(getattr(settings, "SCRAPER_EXECUTION_RETENTION_DAYS", 14)),
            help="Cantidad de dias a conservar.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra cuantos registros se purgarian sin borrar.",
        )

    def handle(self, *args, **options):
        keep_days = max(1, int(options["keep_days"]))
        cutoff = timezone.now() - timedelta(days=keep_days)
        queryset = ScraperExecution.objects.filter(started_at__lt=cutoff)
        count = queryset.count()

        if options["dry_run"]:
            self.stdout.write(f"scraper_executions_to_delete={count} cutoff={cutoff.isoformat()}")
            return

        deleted, _ = queryset.delete()
        self.stdout.write(self.style.SUCCESS(f"scraper_executions_deleted={deleted} cutoff={cutoff.isoformat()}"))
