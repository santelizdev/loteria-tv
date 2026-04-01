from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from core.models import ScraperExecution


class ScraperExecutionRetentionService:
    @classmethod
    def prune_old_executions(cls, *, keep_days: int = 2) -> int:
        keep_days = max(1, int(keep_days))
        cutoff_date = timezone.localdate() - timedelta(days=keep_days - 1)
        queryset = ScraperExecution.objects.filter(draw_date__lt=cutoff_date)
        deleted_count, _ = queryset.delete()
        return deleted_count
