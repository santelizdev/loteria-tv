# core/services/device_redis_service.py

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

try:
    # django-redis
    from django_redis import get_redis_connection
except Exception:  # pragma: no cover
    get_redis_connection = None


class DeviceRedisService:
    """
    Wrapper único para:
      - heartbeats de dispositivos
      - cache de endpoints (results/animalitos)
      - invalidación por key y por patrón

    Importante:
      - Usa Django cache como fuente principal (CACHES=django_redis).
      - delete_pattern requiere cliente redis real; si no existe, no rompe: retorna 0.
    """

    TTL_SECONDS = 90
    DEFAULT_REDIS_ALIAS = "default"

    @staticmethod
    def _device_key(activation_code: str) -> str:
        return f"device:{activation_code}"

    # -------------------------
    # Redis client helpers
    # -------------------------
    @classmethod
    def get_client(cls):
        """
        Devuelve un cliente Redis (django-redis) para SCAN/DEL por patrón.
        """
        if get_redis_connection is None:
            raise AttributeError("django-redis is not installed/configured")

        return get_redis_connection(cls.DEFAULT_REDIS_ALIAS)

    # -------------------------
    # Heartbeat
    # -------------------------
    @classmethod
    def heartbeat(cls, *, activation_code: str, ip_address: str, branch_id: int | None):
        key = cls._device_key(activation_code)
        payload = {
            "last_seen": timezone.now().isoformat(),
            "ip": ip_address,
            "branch_id": branch_id,
        }
        cache.set(key, payload, timeout=cls.TTL_SECONDS)

    @classmethod
    def is_online(cls, *, activation_code: str) -> bool:
        return cache.get(cls._device_key(activation_code)) is not None

    @classmethod
    def get_status(cls, *, activation_code: str) -> Optional[dict[str, Any]]:
        return cache.get(cls._device_key(activation_code))

    # -------------------------
    # Generic cache helpers
    # -------------------------
    @staticmethod
    def get_cache(key: str):
        return cache.get(key)

    @staticmethod
    def set_cache(key: str, value, ttl_seconds: int):
        cache.set(key, value, timeout=ttl_seconds)

    @staticmethod
    def delete_cache(key: str) -> int:
        """
        Borra una key puntual. Retorna 1 si borró, 0 si no existía.
        """
        return 1 if cache.delete(key) else 0

    @classmethod
    def delete_pattern(cls, pattern: str) -> int:
        """
        Borra keys por patrón via Redis SCAN (no bloqueante).
        Retorna cantidad de keys borradas.
        """
        try:
            client = cls.get_client()
        except Exception:
            # No hay redis client real (o no es django-redis): no rompas la app.
            return 0

        deleted = 0
        # scan_iter devuelve bytes en redis-py; normalizamos.
        for k in client.scan_iter(match=pattern, count=500):
            deleted += int(client.delete(k) or 0)
        return deleted
