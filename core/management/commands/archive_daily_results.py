from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.models import CurrentResult, ResultArchive, AnimalitoResult, AnimalitoArchive


class Command(BaseCommand):
    help = "Archiva resultados de un día (triples + animalitos) y limpia tablas actuales."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="YYYY-MM-DD (opcional). Si no, usa ayer.")
        parser.add_argument("--keep-current", action="store_true", help="No borra Current/Animalito tras archivar.")

    @transaction.atomic
    def handle(self, *args, **opts):
        # fecha objetivo
        if opts.get("date"):
            target_date = timezone.datetime.fromisoformat(opts["date"]).date()
        else:
            target_date = timezone.localdate() - timezone.timedelta(days=1)

        keep_current = opts.get("keep_current", False)

        # ---------- TRIPLES -> ResultArchive ----------
        triples_qs = (
            CurrentResult.objects
            .select_related("provider")
            .filter(draw_date=target_date)
        )
        triples_count = triples_qs.count()
        created_triples = 0

        for r in triples_qs.iterator():
            _, created = ResultArchive.objects.get_or_create(
                provider=r.provider,
                draw_date=r.draw_date,
                draw_time=r.draw_time,
                defaults={
                    "winning_number": r.winning_number,
                    "image_url": r.image_url or "",
                },
            )
            if created:
                created_triples += 1

        # ---------- ANIMALITOS -> AnimalitoArchive ----------
        ani_qs = (
            AnimalitoResult.objects
            .select_related("provider")
            .filter(draw_date=target_date)
        )
        ani_count = ani_qs.count()
        created_ani = 0

        for a in ani_qs.iterator():
            _, created = AnimalitoArchive.objects.get_or_create(
                provider=a.provider,
                draw_date=a.draw_date,
                draw_time=a.draw_time,
                defaults={
                    "animal_number": a.animal_number,
                    "animal_name": a.animal_name,
                    "animal_image_url": a.animal_image_url,
                    "provider_logo_url": a.provider_logo_url or "",
                },
            )
            if created:
                created_ani += 1

        # ---------- Limpieza ----------
        if not keep_current:
            triples_qs.delete()
            ani_qs.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Archivado {target_date}: "
                f"triples {created_triples}/{triples_count}, "
                f"animalitos {created_ani}/{ani_count}. keep_current={keep_current}"
            )
        )
