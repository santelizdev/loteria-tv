from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import CruzDailyContent
from core.services.scraper_health_service import ScraperHealthService


class Command(BaseCommand):
    help = "Ejecuta scrapers al iniciar el stack si no hay exito reciente del dia en ventana operativa."

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-age-minutes",
            type=int,
            default=int(getattr(settings, "SCRAPER_BOOTSTRAP_MAX_AGE_MINUTES", 90)),
            help="Edad maxima del ultimo OK antes de forzar corrida al arrancar.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        local_now = timezone.localtime(now)
        current_date = local_now.date()
        max_age = timedelta(minutes=max(1, int(options["max_age_minutes"])))

        for scraper_key, definition in ScraperHealthService.REGISTRY.items():
            if not (definition.starts_hour <= local_now.hour <= definition.ends_hour):
                self.stdout.write(f"SKIP {scraper_key}: fuera de ventana operativa.")
                continue

            monitor = ScraperHealthService.get_or_create_monitor(scraper_key)
            last_success_at = monitor.last_success_at
            if not last_success_at:
                self.stdout.write(f"RUN {scraper_key}: sin exito previo registrado.")
                ScraperHealthService.run_registered(scraper_key)
                continue

            last_success_local = timezone.localtime(last_success_at)
            if last_success_local.date() != current_date:
                self.stdout.write(
                    f"RUN {scraper_key}: ultimo OK {last_success_local:%Y-%m-%d %H:%M} fuera del dia actual."
                )
                ScraperHealthService.run_registered(scraper_key)
                continue

            if (now - last_success_at) >= max_age:
                self.stdout.write(
                    f"RUN {scraper_key}: ultimo OK {last_success_local:%H:%M} supera antiguedad maxima."
                )
                ScraperHealthService.run_registered(scraper_key)
                continue

            self.stdout.write(f"SKIP {scraper_key}: ultimo OK reciente {last_success_local:%H:%M}.")

        self._warm_cruz_daily_content(local_now=local_now, current_date=current_date)

    def _warm_cruz_daily_content(self, *, local_now, current_date):
        if local_now.hour < 9:
            self.stdout.write("SKIP cruz_daily_content: aun no inicia la ventana diaria (09:00 Vzla).")
            return

        latest_date = CruzDailyContent.objects.order_by("-draw_date").values_list("draw_date", flat=True).first()
        if latest_date == current_date:
            self.stdout.write(f"SKIP cruz_daily_content: contenido diario ya disponible para {current_date}.")
            return

        self.stdout.write("RUN cruz_daily_content: falta contenido diario vigente.")
        try:
            call_command("scrape_cruz_daily_content")
        except Exception as exc:
            self.stderr.write(f"FAIL cruz_daily_content: {exc}")
