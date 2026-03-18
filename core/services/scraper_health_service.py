from __future__ import annotations

import traceback
from dataclasses import dataclass
from datetime import timedelta

from django.core.management import call_command
from django.utils import timezone

from core.models import ScraperHealth


@dataclass(frozen=True)
class ScraperDefinition:
    key: str
    label: str
    command_name: str
    stale_after_minutes: int = 150
    starts_hour: int = 8
    ends_hour: int = 22


class ScraperHealthService:
    REGISTRY = {
        "lotoven_triples": ScraperDefinition(
            key="lotoven_triples",
            label="Triples Lotoven",
            command_name="scrape_lotoven_tables",
        ),
        "tuazar_triples": ScraperDefinition(
            key="tuazar_triples",
            label="Triples TuAzar",
            command_name="scrape_tuazar_tables",
        ),
        "lotoven_animalitos": ScraperDefinition(
            key="lotoven_animalitos",
            label="Animalitos Lotoven",
            command_name="scrape_lotoven_animalitos",
        ),
        "condor_animalitos": ScraperDefinition(
            key="condor_animalitos",
            label="Animalitos Condor Gana",
            command_name="scrape_condor_animalitos",
        ),
    }

    @classmethod
    def get_definition(cls, scraper_key: str) -> ScraperDefinition:
        try:
            return cls.REGISTRY[scraper_key]
        except KeyError as exc:
            raise KeyError(f"Unknown scraper_key: {scraper_key}") from exc

    @classmethod
    def get_or_create_monitor(cls, scraper_key: str) -> ScraperHealth:
        definition = cls.get_definition(scraper_key)
        monitor, _ = ScraperHealth.objects.get_or_create(
            scraper_key=definition.key,
            defaults={
                "label": definition.label,
                "command_name": definition.command_name,
                "last_status": ScraperHealth.Status.NEVER,
            },
        )
        updates = []
        if monitor.label != definition.label:
            monitor.label = definition.label
            updates.append("label")
        if monitor.command_name != definition.command_name:
            monitor.command_name = definition.command_name
            updates.append("command_name")
        if updates:
            updates.append("updated_at")
            monitor.save(update_fields=updates)
        return monitor

    @classmethod
    def mark_running(cls, scraper_key: str) -> ScraperHealth:
        now = timezone.now()
        monitor = cls.get_or_create_monitor(scraper_key)
        monitor.last_status = ScraperHealth.Status.RUNNING
        monitor.last_started_at = now
        monitor.last_finished_at = None
        monitor.last_error_message = ""
        monitor.last_error_traceback = ""
        monitor.save(
            update_fields=[
                "last_status",
                "last_started_at",
                "last_finished_at",
                "last_error_message",
                "last_error_traceback",
                "updated_at",
            ]
        )
        return monitor

    @classmethod
    def mark_success(cls, scraper_key: str) -> ScraperHealth:
        now = timezone.now()
        monitor = cls.get_or_create_monitor(scraper_key)
        monitor.last_status = ScraperHealth.Status.SUCCESS
        monitor.last_finished_at = now
        monitor.last_success_at = now
        monitor.last_error_message = ""
        monitor.last_error_traceback = ""
        monitor.consecutive_failures = 0
        monitor.save(
            update_fields=[
                "last_status",
                "last_finished_at",
                "last_success_at",
                "last_error_message",
                "last_error_traceback",
                "consecutive_failures",
                "updated_at",
            ]
        )
        return monitor

    @classmethod
    def mark_failure(cls, scraper_key: str, exc: Exception) -> ScraperHealth:
        now = timezone.now()
        monitor = cls.get_or_create_monitor(scraper_key)
        monitor.last_status = ScraperHealth.Status.FAILED
        monitor.last_finished_at = now
        monitor.last_error_message = cls._truncate_error(str(exc) or exc.__class__.__name__)
        monitor.last_error_traceback = traceback.format_exc()
        monitor.consecutive_failures += 1
        monitor.save(
            update_fields=[
                "last_status",
                "last_finished_at",
                "last_error_message",
                "last_error_traceback",
                "consecutive_failures",
                "updated_at",
            ]
        )
        return monitor

    @classmethod
    def run_registered(cls, scraper_key: str):
        definition = cls.get_definition(scraper_key)
        cls.mark_running(scraper_key)
        try:
            result = call_command(definition.command_name)
        except Exception as exc:
            cls.mark_failure(scraper_key, exc)
            raise
        cls.mark_success(scraper_key)
        return result

    @classmethod
    def get_active_alerts(cls, *, now=None) -> list[dict]:
        current_dt = now or timezone.now()
        alerts = []
        for definition in cls.REGISTRY.values():
            monitor = cls.get_or_create_monitor(definition.key)
            alert = cls._build_alert_payload(definition, monitor, current_dt=current_dt)
            if alert:
                alerts.append(alert)
        return alerts

    @classmethod
    def get_alert(cls, scraper_key: str, *, now=None) -> dict | None:
        current_dt = now or timezone.now()
        definition = cls.get_definition(scraper_key)
        monitor = cls.get_or_create_monitor(scraper_key)
        return cls._build_alert_payload(definition, monitor, current_dt=current_dt)

    @classmethod
    def build_admin_summary(cls, *, queryset=None, now=None) -> dict:
        current_dt = now or timezone.now()
        monitors = list(queryset) if queryset is not None else [
            cls.get_or_create_monitor(definition.key)
            for definition in cls.REGISTRY.values()
        ]

        summary = {
            "total": len(monitors),
            "ok": 0,
            "active": 0,
            "failed_today": 0,
            "missing_today": 0,
            "stale": 0,
            "running": 0,
            "never": 0,
        }

        for monitor in monitors:
            alert = cls.get_alert(monitor.scraper_key, now=current_dt)
            if alert:
                summary["active"] += 1
                alert_kind = alert.get("alert_kind")
                if alert_kind in {"failed_today", "missing_today", "stale"}:
                    summary[alert_kind] += 1
            else:
                summary["ok"] += 1

            if monitor.last_status == ScraperHealth.Status.RUNNING:
                summary["running"] += 1
            elif monitor.last_status == ScraperHealth.Status.NEVER:
                summary["never"] += 1

        return summary

    @classmethod
    def _build_alert_payload(
        cls,
        definition: ScraperDefinition,
        monitor: ScraperHealth,
        *,
        current_dt,
    ) -> dict | None:
        local_now = timezone.localtime(current_dt)
        is_business_hours = definition.starts_hour <= local_now.hour <= definition.ends_hour
        current_date = local_now.date()
        last_success_date = (
            timezone.localtime(monitor.last_success_at).date()
            if monitor.last_success_at
            else None
        )
        last_started_date = (
            timezone.localtime(monitor.last_started_at).date()
            if monitor.last_started_at
            else None
        )

        alert_kind = ""
        severity = "warning"
        message = ""
        if monitor.last_status == ScraperHealth.Status.FAILED and last_started_date == current_date:
            alert_kind = "failed_today"
            severity = "critical"
            message = monitor.last_error_message or "La ultima corrida fallo."
        elif is_business_hours and last_success_date != current_date:
            if monitor.last_status == ScraperHealth.Status.RUNNING:
                return None
            alert_kind = "missing_today"
            severity = "critical"
            if monitor.last_success_at:
                last_success_local = timezone.localtime(monitor.last_success_at).strftime("%Y-%m-%d %H:%M")
                message = f"No hay corrida exitosa registrada hoy. Ultimo OK: {last_success_local}."
            else:
                message = "No hay corrida exitosa registrada hoy."
        elif (
            is_business_hours
            and monitor.last_success_at
            and (current_dt - monitor.last_success_at) > timedelta(minutes=definition.stale_after_minutes)
        ):
            alert_kind = "stale"
            minutes = int((current_dt - monitor.last_success_at).total_seconds() // 60)
            message = f"Ultima corrida exitosa hace {minutes} min."

        if not message:
            return None

        return {
            "scraper_key": definition.key,
            "label": definition.label,
            "command_name": definition.command_name,
            "status": monitor.last_status,
            "alert_kind": alert_kind,
            "severity": severity,
            "message": message,
            "last_error_message": monitor.last_error_message,
            "last_started_at": monitor.last_started_at.isoformat() if monitor.last_started_at else None,
            "last_finished_at": monitor.last_finished_at.isoformat() if monitor.last_finished_at else None,
            "last_success_at": monitor.last_success_at.isoformat() if monitor.last_success_at else None,
            "consecutive_failures": monitor.consecutive_failures,
        }

    @staticmethod
    def _truncate_error(text: str, limit: int = 400) -> str:
        value = (text or "").strip()
        if len(value) <= limit:
            return value
        return value[: limit - 3] + "..."
