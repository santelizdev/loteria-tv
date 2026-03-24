from __future__ import annotations

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from core.services.scraper_permission_service import ScraperPermissionService


class Command(BaseCommand):
    help = "Crea y valida los grupos viewer/resolver para operacion de incidentes de scrapers."

    def handle(self, *args, **options):
        viewer_groups = ScraperPermissionService.get_viewer_groups()
        resolver_groups = ScraperPermissionService.get_resolver_groups()

        if not viewer_groups and not resolver_groups:
            self.stdout.write(self.style.WARNING("No hay grupos configurados en settings."))
            return

        created = 0
        for name in viewer_groups + resolver_groups:
            _, was_created = Group.objects.get_or_create(name=name)
            if was_created:
                created += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Scraper ops groups ready. created={created} "
                f"viewers={viewer_groups or ['-']} resolvers={resolver_groups or ['-']}"
            )
        )
