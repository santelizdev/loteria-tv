# core/services/device_redis_service.py

from __future__ import annotations

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
      - heartbeats de dispositivos (online/offline)
      - cache de endpoints (results/animalitos)
      - invalidación por key y por patrón

    Notas importantes:
      - Si hay 2 clases con el mismo nombre en el mismo archivo,
        Python se queda con la última (esto rompía tu comportamiento).
      - Este archivo deja UNA sola clase (fuente de verdad).
    """

    # Heartbeat TTL (online/offline) -> esto sí puede ser más “largo”
    HEARTBEAT_TTL_SECONDS = getattr(settings, "DEVICE_HEARTBEAT_TTL_SECONDS", 90)

    # Cache "resultados" -> por defecto BAJITO (tiempo real)
    # Si quieres apagarlo globalmente: RESULTS_CACHE_TTL_SECONDS=0
    RESULTS_CACHE_TTL_SECONDS = getattr(settings, "RESULTS_CACHE_TTL_SECONDS", 5)

    DEFAULT_REDIS_ALIAS = getattr(settings, "DEVICE_REDIS_ALIAS", "default")

    # -------------------------
    # Redis client helpers
    # -------------------------
    @classmethod
    def get_client(cls):
        """
        Devuelve un cliente Redis (django-redis) para SCAN/DEL por patrón.
        Si no existe (no es django-redis), levanta excepción.
        """
        if get_redis_connection is None:
            raise AttributeError("django-redis is not installed/configured")
        return get_redis_connection(cls.DEFAULT_REDIS_ALIAS)

    # -------------------------
    # Heartbeat
    # -------------------------
    @staticmethod
    def _device_key(activation_code: str) -> str:
        return f"device:{activation_code}"

    @classmethod
    def heartbeat(cls, *, activation_code: str, ip_address: str, branch_id: int | None):
        key = cls._device_key(activation_code)
        payload = {
            "last_seen": timezone.now().isoformat(),
            "ip": ip_address,
            "branch_id": branch_id,
        }
        cache.set(key, payload, timeout=cls.HEARTBEAT_TTL_SECONDS)

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
        """
        Guarda un valor genérico en Redis/Django cache.

        Regla CLAVE (tiempo real):
          - Si ttl_seconds <= 0 => NO cachea (y borra si existía).
        """
        if ttl_seconds is None:
            ttl_seconds = 0

        if int(ttl_seconds) <= 0:
            cache.delete(key)
            return

        cache.set(key, value, timeout=int(ttl_seconds))

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
            return 0

        deleted = 0
        for k in client.scan_iter(match=pattern, count=500):
            deleted += int(client.delete(k) or 0)
        return deleted