from __future__ import annotations

import json

from django.conf import settings
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry

from core.models import DeviceTelemetryEvent
from core.services.scraper_notification_service import ScraperNotificationService


class AdminActivityNotificationService:
    MODEL_LABELS = {
        ("auth", "user"): "Usuario",
        ("auth", "group"): "Grupo",
        ("core", "client"): "Cliente",
        ("core", "branch"): "Sucursal",
        ("core", "device"): "TV",
    }
    DELETE_MODELS = {
        ("auth", "user"),
        ("auth", "group"),
        ("core", "client"),
        ("core", "branch"),
        ("core", "device"),
    }
    ALWAYS_NOTIFY_CHANGES_MODELS = {
        ("auth", "user"),
        ("auth", "group"),
    }
    DEVICE_CHANGE_FIELDS = {"branch", "is active", "is_active", "registered ip", "registered_ip"}
    BRANCH_CHANGE_FIELDS = {"paid until", "paid_until", "is active", "is_active"}

    @classmethod
    def is_enabled(cls) -> bool:
        return bool(
            getattr(settings, "ADMIN_ACTIVITY_TELEGRAM_ENABLED", False)
            and ScraperNotificationService.is_telegram_configured()
        )

    @classmethod
    def login_notifications_enabled(cls) -> bool:
        return bool(getattr(settings, "ADMIN_ACTIVITY_LOGIN_TELEGRAM_ENABLED", False))

    @classmethod
    def notify_admin_log_entry(cls, log_entry: LogEntry) -> bool:
        if not cls.is_enabled() or not cls.should_notify_log_entry(log_entry):
            return False

        message = cls.build_admin_log_entry_message(log_entry)
        if not message:
            return False

        ScraperNotificationService._dispatch_message(message)
        return True

    @classmethod
    def notify_user_login(cls, *, user, request) -> bool:
        del user, request
        return False

    @classmethod
    def notify_telemetry_event(cls, event: DeviceTelemetryEvent) -> bool:
        del event
        return False

    @classmethod
    def should_notify_log_entry(cls, log_entry: LogEntry) -> bool:
        content_type = log_entry.content_type
        if not content_type:
            return False

        key = (content_type.app_label, content_type.model)
        if key not in cls.MODEL_LABELS:
            return False

        if log_entry.action_flag == ADDITION:
            return True
        if log_entry.action_flag == DELETION:
            return key in cls.DELETE_MODELS
        if log_entry.action_flag != CHANGE:
            return False

        if key in cls.ALWAYS_NOTIFY_CHANGES_MODELS:
            return True

        changed_fields = cls._extract_changed_fields(log_entry)
        if key == ("core", "branch"):
            return cls._matches_any_field(changed_fields, cls.BRANCH_CHANGE_FIELDS)
        if key == ("core", "device"):
            return cls._matches_any_field(changed_fields, cls.DEVICE_CHANGE_FIELDS)
        return False

    @classmethod
    def build_admin_log_entry_message(cls, log_entry: LogEntry) -> str:
        content_type = log_entry.content_type
        key = (content_type.app_label, content_type.model)
        model_label = cls.MODEL_LABELS.get(key, content_type.model)
        action_label = cls._action_label(log_entry.action_flag)
        lines = [
            "LoteriaTV - Actividad admin",
            f"Accion: {action_label}",
            f"Usuario: {log_entry.user.username}",
            f"Objeto: {model_label}",
            f"Detalle: {log_entry.object_repr}",
        ]

        changed_fields = cls._extract_changed_fields(log_entry)
        if changed_fields:
            lines.append(f"Campos: {', '.join(changed_fields)}")

        admin_url = cls._build_admin_url(log_entry)
        if admin_url:
            lines.append(f"Admin: {admin_url}")
        return "\n".join(lines)

    @staticmethod
    def _action_label(action_flag: int) -> str:
        if action_flag == ADDITION:
            return "creacion"
        if action_flag == CHANGE:
            return "cambio"
        if action_flag == DELETION:
            return "eliminacion"
        return "actividad"

    @classmethod
    def _extract_changed_fields(cls, log_entry: LogEntry) -> list[str]:
        raw_message = (log_entry.change_message or "").strip()
        if not raw_message:
            return []
        if not raw_message.startswith("["):
            return [raw_message]

        try:
            payload = json.loads(raw_message)
        except json.JSONDecodeError:
            return [raw_message]

        fields: list[str] = []
        for item in payload:
            changed = item.get("changed") or {}
            fields.extend(str(field).strip() for field in changed.get("fields", []) if str(field).strip())
        return fields

    @staticmethod
    def _matches_any_field(changed_fields: list[str], expected_fields: set[str]) -> bool:
        normalized = {
            str(field).strip().lower().replace("_", " ")
            for field in changed_fields
            if str(field).strip()
        }
        normalized_expected = {field.strip().lower().replace("_", " ") for field in expected_fields}
        return not normalized.isdisjoint(normalized_expected)

    @staticmethod
    def _extract_ip(request) -> str:
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0].strip()
        return (request.META.get("REMOTE_ADDR") or "").strip()

    @staticmethod
    def _build_admin_url(log_entry: LogEntry) -> str:
        if log_entry.action_flag == DELETION:
            return ""
        content_type = log_entry.content_type
        if not content_type or not log_entry.object_id:
            return ""
        base_url = getattr(settings, "SCRAPER_ADMIN_BASE_URL", "").rstrip("/")
        if not base_url:
            return ""
        return (
            f"{base_url}/admin/{content_type.app_label}/{content_type.model}/"
            f"{log_entry.object_id}/change/"
        )
