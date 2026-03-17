from __future__ import annotations

from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import OperationalError
from django.db import connection, transaction
from django.utils import timezone

from core.management.command_helpers import raise_database_connection_help
from core.models import (
    CurrentResult,
    ResultArchive,
    AnimalitoResult,
    AnimalitoArchive,
)


class Command(BaseCommand):
    help = (
        "Enforces data retention: keep ONLY today's rows in current tables and ONLY "
        "yesterday's rows in archive tables. Deletes everything else. Optionally VACUUM for SQLite."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Do not delete, only show counts.")
        parser.add_argument(
            "--keep-archive-days",
            type=int,
            default=1,
            help="How many days to keep in archive tables (default: 1 = yesterday only).",
        )
        parser.add_argument(
            "--vacuum",
            action="store_true",
            help="Run VACUUM after deletions (SQLite only).",
        )
        parser.add_argument(
            "--skip-safety-checks",
            action="store_true",
            help="Skip safety checks that require yesterday rows to exist in archive tables.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        keep_archive_days: int = options["keep_archive_days"]
        vacuum: bool = options["vacuum"]
        skip_safety_checks: bool = options["skip_safety_checks"]

        if keep_archive_days < 1:
            raise ValueError("--keep-archive-days must be >= 1")

        today = timezone.localdate()
        # archive window: keep [today - keep_archive_days, today - 1]
        archive_start = today - timedelta(days=keep_archive_days)
        archive_end = today - timedelta(days=1)

        self.stdout.write(f"today={today} | keep archive range: {archive_start}..{archive_end}")
        self.stdout.write(f"dry_run={dry_run} vacuum={vacuum} skip_safety_checks={skip_safety_checks}")

        try:
            if not skip_safety_checks:
                archive_triples_yesterday = ResultArchive.objects.filter(draw_date=archive_end).count()
                archive_animalitos_yesterday = AnimalitoArchive.objects.filter(draw_date=archive_end).count()

                if archive_triples_yesterday == 0 or archive_animalitos_yesterday == 0:
                    message = (
                        "SAFETY CHECK FAILED: retention aborted because archive tables do not have complete "
                        f"yesterday data (triples={archive_triples_yesterday}, "
                        f"animalitos={archive_animalitos_yesterday}, expected > 0)."
                    )
                    self.stderr.write(self.style.ERROR(message))
                    raise SystemExit(2)

            # Compute what would be deleted
            to_delete = [
                ("CurrentResult", CurrentResult.objects.exclude(draw_date=today)),
                ("AnimalitoResult", AnimalitoResult.objects.exclude(draw_date=today)),
                ("ResultArchive", ResultArchive.objects.exclude(draw_date__range=(archive_start, archive_end))),
                ("AnimalitoArchive", AnimalitoArchive.objects.exclude(draw_date__range=(archive_start, archive_end))),
            ]

            for name, qs in to_delete:
                self.stdout.write(f"{name}: would delete {qs.count()} rows")
        except OperationalError as exc:
            raise_database_connection_help(command_name="enforce_retention --dry-run", exc=exc)

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run: no changes applied."))
            return

        with transaction.atomic():
            for name, qs in to_delete:
                deleted_count, _ = qs.delete()
                self.stdout.write(self.style.SUCCESS(f"{name}: deleted {deleted_count} rows"))

        if vacuum:
            if connection.vendor == "sqlite":
                self.stdout.write("Running SQLite VACUUM...")
                with connection.cursor() as cursor:
                    cursor.execute("VACUUM;")
                self.stdout.write(self.style.SUCCESS("VACUUM done."))
            else:
                self.stdout.write(self.style.WARNING("VACUUM skipped: not SQLite."))

        self.stdout.write(self.style.SUCCESS("Retention enforcement completed."))
