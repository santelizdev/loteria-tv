from django.core.management.base import BaseCommand
from core.models import CurrentResult


class Command(BaseCommand):
    help = "Clear all daily lottery results (CurrentResult table)"

    def handle(self, *args, **options):
        count = CurrentResult.objects.count()
        CurrentResult.objects.all().delete()

        self.stdout.write(
            self.style.SUCCESS(
                f"Daily results cleared successfully ({count} records deleted)"
            )
        )
