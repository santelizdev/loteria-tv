from __future__ import annotations

from django.db import transaction

from core.models import CurrentResult
from core.models.animalito_result import AnimalitoResult
from core.ws.events import broadcast_results_refresh_now


class ResultsRefreshService:
    @staticmethod
    def _upsert(model_class, *, lookup: dict, defaults: dict):
        obj = model_class.objects.filter(**lookup).first()
        if obj is None:
            created = model_class.objects.create(**lookup, **defaults)
            return created, True, True

        changed_fields: list[str] = []
        for field_name, expected_value in defaults.items():
            if getattr(obj, field_name) != expected_value:
                setattr(obj, field_name, expected_value)
                changed_fields.append(field_name)

        if changed_fields:
            obj.save(update_fields=changed_fields)
            return obj, False, True

        return obj, False, False

    @classmethod
    def upsert_current_result(
        cls,
        *,
        provider,
        draw_date,
        draw_time,
        defaults: dict,
    ):
        return cls._upsert(
            CurrentResult,
            lookup={
                "provider": provider,
                "draw_date": draw_date,
                "draw_time": draw_time,
            },
            defaults=defaults,
        )

    @classmethod
    def upsert_animalito_result(
        cls,
        *,
        provider,
        draw_date,
        draw_time,
        defaults: dict,
    ):
        return cls._upsert(
            AnimalitoResult,
            lookup={
                "provider": provider,
                "draw_date": draw_date,
                "draw_time": draw_time,
            },
            defaults=defaults,
        )

    @staticmethod
    def schedule_refresh_results_now_on_commit(*, has_changes: bool) -> None:
        if not has_changes:
            return
        transaction.on_commit(broadcast_results_refresh_now)
