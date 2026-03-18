from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.db import OperationalError
from django.db.models import Count
from django.utils import timezone

from core.management.command_helpers import raise_database_connection_help
from core.models import AnimalitoArchive, AnimalitoResult, CurrentResult, ResultArchive
from core.services.scraper_health_service import ScraperHealthService


@dataclass
class TableCheck:
    name: str
    model: type


TABLES = (
    TableCheck("CurrentResult", CurrentResult),
    TableCheck("AnimalitoResult", AnimalitoResult),
    TableCheck("ResultArchive", ResultArchive),
    TableCheck("AnimalitoArchive", AnimalitoArchive),
)


class Command(BaseCommand):
    help = (
        "Checks operational data health: distinct draw_date cardinality per table, "
        "today row counts and yesterday archive coverage."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-distinct-dates",
            type=int,
            default=1,
            help="Maximum allowed distinct draw_date values per table (default: 1).",
        )
        parser.add_argument(
            "--skip-scrapers",
            action="store_true",
            help="Skip scraper health checks and only validate result tables.",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Exit with non-zero status if any check fails.",
        )

    def handle(self, *args, **options):
        max_distinct_dates = int(options["max_distinct_dates"])
        skip_scrapers = bool(options["skip_scrapers"])
        strict = bool(options["strict"])

        today = timezone.localdate()
        yesterday = today - timezone.timedelta(days=1)
        current_dt = timezone.now()

        failures: list[str] = []

        self.stdout.write(f"today={today} yesterday={yesterday}")

        try:
            for table in TABLES:
                distinct_dates = table.model.objects.values("draw_date").distinct().count()
                total_rows = table.model.objects.count()
                top_dates = list(
                    table.model.objects.values("draw_date")
                    .annotate(c=Count("id"))
                    .order_by("-draw_date")[:5]
                )

                self.stdout.write(
                    f"{table.name}: rows={total_rows} distinct_draw_dates={distinct_dates} recent={top_dates}"
                )

                if distinct_dates > max_distinct_dates:
                    failures.append(
                        f"{table.name} has {distinct_dates} distinct draw_date values (> {max_distinct_dates})"
                    )

            today_triples = CurrentResult.objects.filter(draw_date=today).count()
            today_animalitos = AnimalitoResult.objects.filter(draw_date=today).count()
            yesterday_archive_triples = ResultArchive.objects.filter(draw_date=yesterday).count()
            yesterday_archive_animalitos = AnimalitoArchive.objects.filter(draw_date=yesterday).count()
        except OperationalError as exc:
            raise_database_connection_help(command_name="check_ops_health", exc=exc)

        self.stdout.write(
            f"CurrentResult(today)={today_triples} | AnimalitoResult(today)={today_animalitos}"
        )
        self.stdout.write(
            f"ResultArchive(yesterday)={yesterday_archive_triples} | "
            f"AnimalitoArchive(yesterday)={yesterday_archive_animalitos}"
        )

        if today_triples == 0:
            failures.append("CurrentResult has 0 rows for today")
        if today_animalitos == 0:
            failures.append("AnimalitoResult has 0 rows for today")
        if yesterday_archive_triples == 0:
            failures.append("ResultArchive has 0 rows for yesterday")
        if yesterday_archive_animalitos == 0:
            failures.append("AnimalitoArchive has 0 rows for yesterday")

        if not skip_scrapers:
            self.stdout.write("")
            self.stdout.write("Scraper health:")
            summary = ScraperHealthService.build_admin_summary(now=current_dt)
            self.stdout.write(
                "summary: "
                f"total={summary['total']} ok={summary['ok']} active={summary['active']} "
                f"failed_today={summary['failed_today']} missing_today={summary['missing_today']} "
                f"stale={summary['stale']} running={summary['running']} never={summary['never']}"
            )

            for definition in ScraperHealthService.REGISTRY.values():
                monitor = ScraperHealthService.get_or_create_monitor(definition.key)
                alert = ScraperHealthService.get_alert(definition.key, now=current_dt)
                alert_label = f"{alert['alert_kind']}: {alert['message']}" if alert else "OK"
                self.stdout.write(
                    f"{definition.key}: status={monitor.last_status} "
                    f"last_success={monitor.last_success_at} "
                    f"last_finished={monitor.last_finished_at} "
                    f"failures={monitor.consecutive_failures} "
                    f"alert={alert_label}"
                )
                if alert:
                    failures.append(
                        f"Scraper {definition.key} has active alert [{alert['alert_kind']}]: {alert['message']}"
                    )

        if failures:
            for failure in failures:
                self.stderr.write(self.style.ERROR(f"FAIL: {failure}"))

            if strict:
                raise SystemExit(1)

            self.stdout.write(self.style.WARNING("Completed with failures (non-strict mode)."))
            return

        self.stdout.write(self.style.SUCCESS("All health checks passed."))
