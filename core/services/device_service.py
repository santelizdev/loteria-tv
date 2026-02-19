# core/services/device_service.py

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from core.models import Device
from core.services.device_redis_service import DeviceRedisService


class DeviceService:
    LAST_SEEN_DB_EVERY_SECONDS = 300  # 5 min

    @staticmethod
    def _should_update_last_seen_db(activation_code: str) -> bool:
        key = f"device:last_seen_db:{activation_code}"
        return cache.add(key, "1", timeout=DeviceService.LAST_SEEN_DB_EVERY_SECONDS)

    @staticmethod
    def validate_device(*, activation_code: str, ip_address: str) -> Device:
        """
        Valida device y branch (y registra heartbeat).
        - NO bloquea por IP.
        - Si registered_ip está vacío, lo setea.
        - Si cambia, lo actualiza (solo como dato, sin prohibir).
        """
        activation_code = (activation_code or "").strip()
        if not activation_code:
            raise PermissionError("Missing activation code")

        try:
            device = Device.objects.select_related("branch__client").get(
                activation_code=activation_code
            )
        except Device.DoesNotExist:
            raise PermissionError("Invalid activation code")

        # Reglas de negocio
        if not device.branch:
            raise PermissionError("Device not assigned to a branch")

        if not (device.branch.is_active and device.branch.is_payment_valid()):
            raise PermissionError("Branch subscription expired or inactive")

        if not device.is_active:
            raise PermissionError("Device is inactive")

        # IP: solo informativo
        ip_address = (ip_address or "").strip()
        if ip_address:
            if not device.registered_ip:
                device.registered_ip = ip_address
                device.save(update_fields=["registered_ip"])
            elif device.registered_ip != ip_address:
                # actualiza (no bloquea)
                device.registered_ip = ip_address
                device.save(update_fields=["registered_ip"])

        # Heartbeat SIEMPRE
        DeviceRedisService.heartbeat(
            activation_code=device.activation_code,
            ip_address=ip_address,
            branch_id=device.branch_id,
        )

        # last_seen en DB solo cada X minutos
        if DeviceService._should_update_last_seen_db(device.activation_code):
            device.last_seen = timezone.now()
            device.save(update_fields=["last_seen"])

        return device
