from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import CurrentResult, ResultArchive


class Command(BaseCommand):
    help = "Archiva TRIPLES del día objetivo (por defecto ayer) a ResultArchive y limpia CurrentResult."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="YYYY-MM-DD (opcional). Si no, usa ayer.")
        parser.add_argument("--keep-current", action="store_true", help="No borra CurrentResult al finalizar.")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts.get("date"):
            target_date = timezone.datetime.fromisoformat(opts["date"]).date()
        else:
            target_date = timezone.localdate() - timezone.timedelta(days=1)

        keep_current = bool(opts.get("keep_current", False))

        qs = CurrentResult.objects.select_related("provider").filter(draw_date=target_date)
        total = qs.count()

        created = 0
        updated = 0

        for r in qs.iterator():
            _, was_created = ResultArchive.objects.update_or_create(
                provider=r.provider,
                draw_date=r.draw_date,
                draw_time=r.draw_time,
                defaults={
                    "winning_number": r.winning_number,
                    "image_url": r.image_url or "",
                    "extra": r.extra, 
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
                f"Archivado TRIPLES {target_date}: created={created}, updated={updated}, total_src={total}, keep_current={keep_current}"
            )
        )
