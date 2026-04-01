from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone

from core.models import ScraperHealth, ScraperIncident
from core.services.scraper_health_service import ScraperHealthService

@dataclass(frozen=True)
class NotificationDecision:
    monitor: ScraperHealth
    signature: str
    alert: dict


@dataclass(frozen=True)
class IncidentNotificationDecision:
    incident: ScraperIncident
    message: str


class ScraperNotificationService:
    @classmethod
    def get_recipients(cls) -> list[str]:
        return cls._normalize_recipients(getattr(settings, "SCRAPER_TELEGRAM_CHAT_IDS", []))

    @classmethod
    def get_cooldown(cls) -> timedelta:
        minutes = int(getattr(settings, "SCRAPER_ALERT_NOTIFY_COOLDOWN_MINUTES", 180))
        return timedelta(minutes=max(1, minutes))

    @classmethod
    def is_telegram_configured(cls) -> bool:
        return bool(cls.get_recipients() and cls.get_bot_token())

    @classmethod
    def get_bot_token(cls) -> str:
        return getattr(settings, "SCRAPER_TELEGRAM_BOT_TOKEN", "").strip()

    @classmethod
    def collect_pending_notifications(cls, *, now=None, monitors=None, force=False) -> list[NotificationDecision]:
        current_dt = now or timezone.now()
        decisions: list[NotificationDecision] = []
        cooldown = cls.get_cooldown()
        active_alerts = cls._collect_alerts(monitors=monitors, now=current_dt)

        for alert in active_alerts:
            monitor = ScraperHealthService.get_or_create_monitor(alert["scraper_key"])
            signature = cls.build_signature(alert)
            should_notify = bool(force)

            if monitor.last_notified_signature != signature:
                should_notify = True
            elif not monitor.last_notified_at:
                should_notify = True
            elif (current_dt - monitor.last_notified_at) >= cooldown:
                should_notify = True

            if should_notify:
                decisions.append(NotificationDecision(monitor=monitor, signature=signature, alert=alert))

        return decisions

    @classmethod
    def notify_active_alerts(cls, *, now=None, monitors=None, force=False) -> int:
        if not cls.is_telegram_configured():
            return 0

        current_dt = now or timezone.now()
        decisions = cls.collect_pending_notifications(now=current_dt, monitors=monitors, force=force)
        if not decisions:
            return 0

        message = cls.build_health_message(decisions, current_dt)
        cls._dispatch_message(message)

        for decision in decisions:
            decision.monitor.last_notified_at = current_dt
            decision.monitor.last_notified_signature = decision.signature
            decision.monitor.save(update_fields=["last_notified_at", "last_notified_signature", "updated_at"])

        return len(decisions)

    @classmethod
    def collect_pending_incident_notifications(
        cls,
        *,
        incidents=None,
        now=None,
        force=False,
    ) -> list[IncidentNotificationDecision]:
        current_dt = now or timezone.now()
        queryset = cls._normalize_incidents(incidents)
        if not force:
            queryset = [incident for incident in queryset if not incident.alert_sent]
        decisions: list[IncidentNotificationDecision] = []
        seen_keys: set[tuple[str, str, str, str, str]] = set()
        for incident in queryset:
            if incident.status != ScraperIncident.Status.OPEN:
                continue
            if not force and not cls._is_incident_ready_for_notification(incident, now=current_dt):
                continue
            dedupe_key = cls._incident_notification_key(incident)
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            decisions.append(
                IncidentNotificationDecision(
                    incident=incident,
                    message=cls.build_incident_message(incident),
                )
            )
        return decisions

    @classmethod
    def notify_pending_incidents(cls, *, incidents=None, now=None, force=False) -> int:
        if not cls.is_telegram_configured():
            return 0

        current_dt = now or timezone.now()
        decisions = cls.collect_pending_incident_notifications(
            incidents=incidents,
            now=current_dt,
            force=force,
        )
        if not decisions:
            return 0

        sent = 0
        for decision in decisions:
            cls._dispatch_message(decision.message)
            cls._mark_incident_notification_group_sent(
                incident=decision.incident,
                sent_at=current_dt,
            )
            sent += 1
        return sent

    @classmethod
    def mark_current_health_alert_as_notified(cls, scraper_key: str, *, now=None) -> None:
        current_dt = now or timezone.now()
        alert = ScraperHealthService.get_alert(scraper_key, now=current_dt)
        if not alert:
            return
        monitor = ScraperHealthService.get_or_create_monitor(scraper_key)
        monitor.last_notified_at = current_dt
        monitor.last_notified_signature = cls.build_signature(alert)
        monitor.save(update_fields=["last_notified_at", "last_notified_signature", "updated_at"])

    @staticmethod
    def _normalize_recipients(value) -> list[str]:
        if isinstance(value, str):
            raw_values = value.split(",")
        else:
            raw_values = value or []
        return [str(entry).strip() for entry in raw_values if str(entry).strip()]

    @classmethod
    def _collect_alerts(cls, *, monitors=None, now=None) -> list[dict]:
        current_dt = now or timezone.now()
        if monitors is None:
            return ScraperHealthService.get_active_alerts(now=current_dt)

        alerts = []
        for monitor in monitors:
            alert = ScraperHealthService.get_alert(monitor.scraper_key, now=current_dt)
            if alert:
                alerts.append(alert)
        return alerts

    @staticmethod
    def build_signature(alert: dict) -> str:
        return "|".join(
            [
                str(alert.get("scraper_key") or ""),
                str(alert.get("alert_kind") or ""),
                str(alert.get("status") or ""),
                str(alert.get("message") or ""),
                str(alert.get("last_error_message") or ""),
                str(alert.get("last_success_at") or ""),
            ]
        )

    @staticmethod
    def build_health_message(decisions: list[NotificationDecision], current_dt) -> str:
        lines = [
            "LoteriaTV - Alertas activas de scrapers",
            f"Fecha: {timezone.localtime(current_dt).strftime('%Y-%m-%d %H:%M:%S %Z')}",
            "",
        ]
        for decision in decisions:
            alert = decision.alert
            lines.extend(
                [
                    f"* {alert['label']}",
                    f"  tipo: {alert.get('alert_kind') or '-'}",
                    f"  estado: {alert.get('status') or '-'}",
                    f"  mensaje: {alert.get('message') or '-'}",
                    f"  error: {alert.get('last_error_message') or '-'}",
                    f"  ultimo_ok: {alert.get('last_success_at') or '-'}",
                    f"  fallas_consecutivas: {alert.get('consecutive_failures') or 0}",
                    "",
                ]
            )
        return "\n".join(lines).strip()

    @classmethod
    def _incident_notification_key(cls, incident: ScraperIncident) -> tuple[str, str, str, str, str]:
        provider_name = (incident.provider_name or "").strip()
        return (
            incident.scraper_key or "",
            incident.draw_date.isoformat() if incident.draw_date else "",
            provider_name,
            incident.failure_reason_code or "",
            incident.contingency_stage or "",
        )

    @classmethod
    def _mark_incident_notification_group_sent(cls, *, incident: ScraperIncident, sent_at) -> None:
        filters = {
            "scraper_key": incident.scraper_key,
            "draw_date": incident.draw_date,
            "status": ScraperIncident.Status.OPEN,
            "failure_reason_code": incident.failure_reason_code,
            "contingency_stage": incident.contingency_stage,
            "provider_name": incident.provider_name or "",
        }
        ScraperIncident.objects.filter(**filters).update(
            alert_sent=True,
            alert_sent_at=sent_at,
        )

    @classmethod
    def build_incident_message(cls, incident: ScraperIncident) -> str:
        title = "LoteriaTV - Incidente de scraper"
        if incident.failure_reason_code == "command_failed":
            title = "LoteriaTV - Falla critica de scraper"
        elif incident.contingency_stage == ScraperIncident.ContingencyStage.FALLBACK_ACTIVE:
            title = "LoteriaTV - Scraper de emergencia activado"
        elif incident.contingency_stage == ScraperIncident.ContingencyStage.MANUAL_REQUIRED:
            title = "LoteriaTV - Carga manual requerida"

        lines = [
            title,
            f"Incidente: #{incident.id}",
            f"Scraper: {incident.label}",
            f"Fecha objetivo: {incident.draw_date}",
            f"Estado: {incident.status}",
            f"Severidad: {incident.severity or '-'}",
            f"Motivo: {incident.failure_reason_code or '-'}",
            f"Etapa: {incident.contingency_stage or '-'}",
            f"Grupo: {cls._build_incident_target(incident)}",
            f"Intentos principal: {incident.primary_attempt_count}",
            f"Intentos emergencia: {incident.fallback_attempt_count}",
            f"Resumen: {incident.summary or '-'}",
            f"Evidencia: {incident.evidence_summary or '-'}",
        ]
        if incident.fallback_scraper_key:
            lines.append(f"Fallback: {incident.fallback_scraper_key}")
        admin_url = cls.build_incident_admin_url(incident)
        if admin_url:
            lines.append(f"Admin: {admin_url}")
        return "\n".join(lines)

    @classmethod
    def build_incident_admin_url(cls, incident: ScraperIncident) -> str:
        base_url = getattr(settings, "SCRAPER_ADMIN_BASE_URL", "").rstrip("/")
        if not base_url:
            return ""
        return f"{base_url}/admin/core/scraperincident/{incident.pk}/change/"

    @staticmethod
    def _build_incident_target(incident: ScraperIncident) -> str:
        provider_name = incident.provider_name or "scraper"
        draw_time = incident.draw_time.strftime("%H:%M") if incident.draw_time else "-"
        return f"{provider_name} @ {draw_time}"

    @classmethod
    def _is_incident_ready_for_notification(cls, incident: ScraperIncident, *, now) -> bool:
        del now
        if incident.failure_reason_code == "command_failed":
            return True
        if incident.contingency_stage == ScraperIncident.ContingencyStage.FALLBACK_ACTIVE:
            return True
        if incident.contingency_stage == ScraperIncident.ContingencyStage.MANUAL_REQUIRED:
            return True
        return False

    @classmethod
    def _dispatch_message(cls, message: str) -> None:
        bot_token = cls.get_bot_token()
        base_url = getattr(settings, "SCRAPER_TELEGRAM_API_BASE_URL", "https://api.telegram.org").rstrip("/")
        url = f"{base_url}/bot{bot_token}/sendMessage"
        for chat_id in cls.get_recipients():
            response = requests.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": message,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            response.raise_for_status()

    @staticmethod
    def _normalize_incidents(incidents) -> list[ScraperIncident]:
        if incidents is None:
            return list(
                ScraperIncident.objects.filter(status=ScraperIncident.Status.OPEN).order_by("last_detected_at")
            )
        if isinstance(incidents, ScraperIncident):
            return [incidents]
        return list(incidents)
