from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db.models import Q
from django.utils import timezone

from core.models import ScraperHealth
from core.services.scraper_health_service import ScraperHealthService


@dataclass(frozen=True)
class NotificationDecision:
    monitor: ScraperHealth
    signature: str
    alert: dict


class ScraperNotificationService:
    @classmethod
    def get_recipients(cls) -> list[str]:
        recipients = set(cls._normalize_recipients(getattr(settings, "SCRAPER_ALERT_EMAILS", [])))
        recipients.update(user.email for user in cls.get_recipient_users() if user.email)
        return sorted(recipients)

    @classmethod
    def get_recipient_users(cls):
        usernames = cls._normalize_recipients(getattr(settings, "SCRAPER_ALERT_USERNAMES", []))
        groups = cls._normalize_recipients(getattr(settings, "SCRAPER_ALERT_GROUPS", []))

        if not usernames and not groups:
            return get_user_model().objects.none()

        query = Q(is_active=True)
        recipient_query = Q()
        if usernames:
            recipient_query |= Q(username__in=usernames)
        if groups:
            recipient_query |= Q(groups__name__in=groups)

        return get_user_model().objects.filter(query & recipient_query).exclude(email="").distinct()

    @classmethod
    def get_cooldown(cls) -> timedelta:
        minutes = int(getattr(settings, "SCRAPER_ALERT_NOTIFY_COOLDOWN_MINUTES", 180))
        return timedelta(minutes=max(1, minutes))

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
        recipients = cls.get_recipients()
        if not recipients:
            return 0

        current_dt = now or timezone.now()
        decisions = cls.collect_pending_notifications(now=current_dt, monitors=monitors, force=force)
        if not decisions:
            return 0

        subject = cls.build_subject(decisions)
        message = cls.build_message(decisions, current_dt)

        send_mail(
            subject=subject,
            message=message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            recipient_list=recipients,
            fail_silently=False,
        )

        for decision in decisions:
            decision.monitor.last_notified_at = current_dt
            decision.monitor.last_notified_signature = decision.signature
            decision.monitor.save(update_fields=["last_notified_at", "last_notified_signature", "updated_at"])

        return len(decisions)

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
    def build_subject(decisions: list[NotificationDecision]) -> str:
        count = len(decisions)
        if count == 1:
            return f"[LoteriaTV] Alerta de scraper: {decisions[0].alert['label']}"
        return f"[LoteriaTV] {count} alertas de scrapers activas"

    @staticmethod
    def build_message(decisions: list[NotificationDecision], current_dt) -> str:
        lines = [
            "Se detectaron alertas activas de scrapers.",
            f"Fecha: {timezone.localtime(current_dt).isoformat()}",
            "",
        ]
        for decision in decisions:
            alert = decision.alert
            lines.extend(
                [
                    f"- {alert['label']}",
                    f"  status: {alert.get('status') or '-'}",
                    f"  mensaje: {alert.get('message') or '-'}",
                    f"  error: {alert.get('last_error_message') or '-'}",
                    f"  ultimo_ok: {alert.get('last_success_at') or '-'}",
                    f"  ultimo_inicio: {alert.get('last_started_at') or '-'}",
                    f"  ultimo_fin: {alert.get('last_finished_at') or '-'}",
                    f"  fallas_consecutivas: {alert.get('consecutive_failures') or 0}",
                    "",
                ]
            )
        return "\n".join(lines).strip() + "\n"
