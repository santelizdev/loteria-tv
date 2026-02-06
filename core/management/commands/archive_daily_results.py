from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from core.models import CurrentResult, AnimalitoResult, ResultArchive

class Command(BaseCommand):
    help = "Archiva resultados de ayer (triples + animalitos) a ResultArchive y limpia tablas actuales."

    def add_arguments(self, parser):
        parser.add_argument("--date", help="YYYY-MM-DD (opcional). Si no, usa ayer.")
        parser.add_argument("--keep-current", action="store_true", help="No borra Current/Animalito tras archivar.")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts.get("date"):
            target_date = timezone.datetime.fromisoformat(opts["date"]).date()
        else:
            target_date = timezone.localdate() - timezone.timedelta(days=1)

        keep_current = opts.get("keep_current", False)

        # --------- TRIPLES (CurrentResult) ----------
        triples_qs = CurrentResult.objects.select_related("provider").filter(draw_date=target_date)
        triples_count = triples_qs.count()

        created_triples = 0
        for r in triples_qs.iterator():
            _, created = ResultArchive.objects.get_or_create(
                provider=r.provider,
                variant="triple",
                draw_date=r.draw_date,
                draw_time=r.draw_time,
                defaults={
                    "number": r.winning_number,
                    "zodiac": None,
                    "extra": {"image_url": r.image_url} if r.image_url else None,
                },
            )
            if created:
                created_triples += 1

        # --------- ANIMALITOS (AnimalitoResult) ----------
        ani_qs = AnimalitoResult.objects.select_related("provider").filter(draw_date=target_date)
        ani_count = ani_qs.count()

        created_ani = 0
        for a in ani_qs.iterator():
            _, created = ResultArchive.objects.get_or_create(
                provider=a.provider,
                variant="animalito",
                draw_date=a.draw_date,
                draw_time=a.draw_time,
                defaults={
                    "number": str(a.animal_number),
                    "zodiac": None,
                    "extra": {
                        "animal_name": a.animal_name,
                        "animal_image_url": a.animal_image_url,
                        "provider_logo_url": a.provider_logo_url,
                    },
                },
            )
            if created:
                created_ani += 1

        # Limpieza (si quieres que Current muestre SOLO HOY)
        if not keep_current:
            triples_qs.delete()
            ani_qs.delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Archivado {target_date}: triples {created_triples}/{triples_count}, "
                f"animalitos {created_ani}/{ani_count}. keep_current={keep_current}"
            )
        )
