from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import AnimalitoResult, AnimalitoArchive


class Command(BaseCommand):
    help = "Archiva resultados de animalitos del día objetivo (por defecto ayer) a AnimalitoArchive y limpia AnimalitoResult."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="YYYY-MM-DD (opcional). Si no, usa ayer.")
        parser.add_argument("--keep-current", action="store_true", help="No borra AnimalitoResult al finalizar.")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts.get("date"):
            target_date = timezone.datetime.fromisoformat(opts["date"]).date()
        else:
            target_date = timezone.localdate() - timezone.timedelta(days=1)

        keep_current = bool(opts.get("keep_current", False))

        qs = AnimalitoResult.objects.select_related("provider").filter(draw_date=target_date)
        total = qs.count()

        created = 0
        updated = 0

        for a in qs.iterator():
            _, was_created = AnimalitoArchive.objects.update_or_create(
                provider=a.provider,
                draw_date=a.draw_date,
                draw_time=a.draw_time,
                defaults={
                    "animal_number": a.animal_number,
                    "animal_name": a.animal_name,
                    "animal_image_url": a.animal_image_url or "",
                    "provider_logo_url": a.provider_logo_url or "",
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        if not keep_current:
            qs.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Archivado ANIMALITOS {target_date}: created={created}, updated={updated}, total_src={total}, keep_current={keep_current}"
            )
        )
