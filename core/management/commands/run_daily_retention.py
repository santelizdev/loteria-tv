from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Archiva AYER y luego aplica retencion para conservar solo HOY en current y AYER en archive."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            help="YYYY-MM-DD opcional. Si no se indica, usa ayer segun America/Caracas.",
        )
        parser.add_argument(
            "--keep-archive-days",
            type=int,
            default=1,
            help="Dias a conservar en archive al aplicar retention (default: 1 = ayer).",
        )
        parser.add_argument(
            "--skip-safety-checks",
            action="store_true",
            help="Pasa --skip-safety-checks a enforce_retention.",
        )

    def handle(self, *args, **options):
        target_date = options.get("date") or (
            timezone.localdate() - timezone.timedelta(days=1)
        ).isoformat()
        keep_archive_days = int(options["keep_archive_days"])
        skip_safety_checks = bool(options["skip_safety_checks"])

        self.stdout.write(f"[1] Archive yesterday={target_date}")
        call_command("archive_daily_triples", date=target_date)
        call_command("archive_daily_animalitos", date=target_date)

        self.stdout.write("[2] Enforce retention")
        enforce_kwargs = {"keep_archive_days": keep_archive_days}
        if skip_safety_checks:
            enforce_kwargs["skip_safety_checks"] = True
        call_command("enforce_retention", **enforce_kwargs)

        self.stdout.write(self.style.SUCCESS("OK"))

