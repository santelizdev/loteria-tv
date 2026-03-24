from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from core.models import (
    AnimalitoResult,
    CurrentResult,
    ManualResultIntervention,
    Provider,
    ScraperIncident,
)


class ManualResultInterventionService:
    @classmethod
    @transaction.atomic
    def resolve_incident_manually(cls, *, incident: ScraperIncident, user, cleaned_data: dict):
        if incident.status != ScraperIncident.Status.OPEN:
            raise ValueError("El incidente ya no esta abierto.")

        provider = cleaned_data["provider"]
        draw_date = incident.draw_date
        draw_time = cleaned_data["draw_time"] or incident.draw_time
        note = cleaned_data["note"].strip()

        if not provider:
            raise ValueError("Provider requerido para carga manual.")
        if not draw_time:
            raise ValueError("Horario requerido para carga manual.")

        if incident.result_model == "CurrentResult":
            previous = CurrentResult.objects.filter(
                provider=provider,
                draw_date=draw_date,
                draw_time=draw_time,
            ).first()
            previous_snapshot = cls._snapshot_current(previous) if previous else {}
            preserved_image_url = previous.image_url if previous else ""
            defaults = {
                "winning_number": cleaned_data["winning_number"],
                "image_url": preserved_image_url,
                "extra": cls._build_current_extra(cleaned_data),
                "result_origin": CurrentResult.ResultOrigin.MANUAL_CONTINGENCY,
                "source_incident": incident,
            }
            result_obj, created = CurrentResult.objects.update_or_create(
                provider=provider,
                draw_date=draw_date,
                draw_time=draw_time,
                defaults=defaults,
            )
            new_snapshot = cls._snapshot_current(result_obj)
            result_model = ManualResultIntervention.ResultModel.CURRENT_RESULT
        elif incident.result_model == "AnimalitoResult":
            previous = AnimalitoResult.objects.filter(
                provider=provider,
                draw_date=draw_date,
                draw_time=draw_time,
            ).first()
            previous_snapshot = cls._snapshot_animalito(previous) if previous else {}
            preserved_animal_image_url = previous.animal_image_url if previous else ""
            resolved_provider_logo_url = provider.logo_url or (
                previous.provider_logo_url if previous else ""
            )
            defaults = {
                "animal_number": cleaned_data["animal_number"],
                "animal_name": cleaned_data["animal_name"],
                "animal_image_url": preserved_animal_image_url,
                "provider_logo_url": resolved_provider_logo_url,
                "result_origin": AnimalitoResult.ResultOrigin.MANUAL_CONTINGENCY,
                "source_incident": incident,
            }
            result_obj, created = AnimalitoResult.objects.update_or_create(
                provider=provider,
                draw_date=draw_date,
                draw_time=draw_time,
                defaults=defaults,
            )
            new_snapshot = cls._snapshot_animalito(result_obj)
            result_model = ManualResultIntervention.ResultModel.ANIMALITO_RESULT
        else:
            raise ValueError(f"Modelo no soportado para intervencion manual: {incident.result_model}")

        intervention = ManualResultIntervention.objects.create(
            incident=incident,
            result_model=result_model,
            action_type=(
                ManualResultIntervention.ActionType.CREATE
                if created
                else ManualResultIntervention.ActionType.REPLACE
            ),
            provider=provider,
            draw_date=draw_date,
            draw_time=draw_time,
            previous_snapshot=previous_snapshot,
            new_snapshot=new_snapshot,
            note=note,
            performed_by=user,
            performed_at=timezone.now(),
        )

        incident.status = ScraperIncident.Status.RESOLVED
        incident.resolved_at = timezone.now()
        incident.resolved_by = user
        incident.resolution_note = (
            f"Resuelto por carga manual controlada. Intervention #{intervention.pk}. {note}"
        )
        incident.save(update_fields=["status", "resolved_at", "resolved_by", "resolution_note", "updated_at"])
        return intervention

    @staticmethod
    def _build_current_extra(cleaned_data: dict) -> dict | None:
        signo = (cleaned_data.get("signo") or "").strip()
        if not signo:
            return None
        return {"signo": signo}

    @staticmethod
    def _snapshot_current(obj: CurrentResult | None) -> dict:
        if not obj:
            return {}
        return {
            "provider_id": obj.provider_id,
            "provider_name": obj.provider.name,
            "draw_date": obj.draw_date.isoformat(),
            "draw_time": obj.draw_time.strftime("%H:%M"),
            "winning_number": obj.winning_number,
            "image_url": obj.image_url,
            "extra": obj.extra or {},
            "result_origin": obj.result_origin,
            "source_incident_id": obj.source_incident_id,
        }

    @staticmethod
    def _snapshot_animalito(obj: AnimalitoResult | None) -> dict:
        if not obj:
            return {}
        return {
            "provider_id": obj.provider_id,
            "provider_name": obj.provider.name,
            "draw_date": obj.draw_date.isoformat(),
            "draw_time": obj.draw_time.strftime("%H:%M"),
            "animal_number": obj.animal_number,
            "animal_name": obj.animal_name,
            "animal_image_url": obj.animal_image_url,
            "provider_logo_url": obj.provider_logo_url,
            "result_origin": obj.result_origin,
            "source_incident_id": obj.source_incident_id,
        }
