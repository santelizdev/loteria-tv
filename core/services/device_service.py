# core/services/device_service.py

from __future__ import annotations

from typing import Iterable

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
    def _bypass_codes() -> set[str]:
        raw = getattr(settings, "DEVICE_BYPASS_CODES", "") or ""
        return {c.strip().upper() for c in raw.split(",") if c.strip()}

    @staticmethod
    def _is_bypassed(activation_code: str) -> bool:
        # Solo permitimos bypass cuando DEBUG=True
        if not settings.DEBUG:
            return False
        return activation_code.strip().upper() in DeviceService._bypass_codes()

    @staticmethod
    def validate_device(*, activation_code: str, ip_address: str) -> Device:
        """
        Valida device, branch, IP y registra heartbeat.
        Si activation_code está en DEVICE_BYPASS_CODES (solo DEBUG), permite pasar sin branch.
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

        bypass = DeviceService._is_bypassed(activation_code)

        if not bypass:
            if not device.branch:
                raise PermissionError("Device not assigned to a branch")

            if not (device.branch.is_active and device.branch.is_payment_valid()):
                raise PermissionError("Branch subscription expired or inactive")

            if not device.is_active:
                raise PermissionError("Device is inactive")

            # IP fija
            if device.registered_ip:
                if device.registered_ip != ip_address:
                    raise PermissionError("IP address mismatch for this device")
            else:
                device.registered_ip = ip_address
                device.save(update_fields=["registered_ip"])
        else:
            # En bypass: igual dejamos el IP registrado si está vacío, para que no sea caos
            if not device.registered_ip:
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
