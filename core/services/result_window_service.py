from __future__ import annotations

from datetime import time

from django.utils import timezone


def get_business_cutoff_time() -> time:
    now_local = timezone.localtime(timezone.now())
    return now_local.replace(second=0, microsecond=0).time()


def delete_future_rows_for_provider(*, model, provider, draw_date, cutoff_time: time) -> int:
    deleted, _ = model.objects.filter(
        provider=provider,
        draw_date=draw_date,
        draw_time__gt=cutoff_time,
    ).delete()
    return deleted
