from __future__ import annotations

from django.conf import settings


class ScraperPermissionService:
    @classmethod
    def get_viewer_groups(cls) -> list[str]:
        return list(getattr(settings, "SCRAPER_INCIDENT_VIEWER_GROUPS", []) or [])

    @classmethod
    def get_resolver_groups(cls) -> list[str]:
        return list(getattr(settings, "SCRAPER_INCIDENT_RESOLVER_GROUPS", []) or [])

    @classmethod
    def user_can_view_incidents(cls, user) -> bool:
        if not getattr(user, "is_authenticated", False) or not getattr(user, "is_staff", False):
            return False
        if user.is_superuser:
            return True
        groups = cls.get_viewer_groups() + cls.get_resolver_groups()
        if not groups:
            return user.is_staff
        return user.groups.filter(name__in=groups).exists()

    @classmethod
    def user_can_resolve_incidents(cls, user) -> bool:
        if not getattr(user, "is_authenticated", False) or not getattr(user, "is_staff", False):
            return False
        if user.is_superuser:
            return True
        groups = cls.get_resolver_groups()
        if not groups:
            return user.is_staff
        return user.groups.filter(name__in=groups).exists()
