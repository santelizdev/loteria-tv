# core/services/device_redis_service.py

from django.core.cache import cache
from django.utils import timezone

class DeviceRedisService:
    """
    Maneja el estado en tiempo real de los devices usando Redis
    """

    TTL_SECONDS = 90

    @staticmethod
    def _key(activation_code: str) -> str:
        return f"device:{activation_code}"

    @classmethod
    def heartbeat(cls, *, activation_code: str, ip_address: str, branch_id: int):
        key = cls._key(activation_code)

        data = {
            "last_seen": timezone.now().isoformat(),
            "ip": ip_address,
            "branch_id": branch_id,
        }

        cache.set(key, data, timeout=cls.TTL_SECONDS)

    @classmethod
    def is_online(cls, *, activation_code: str) -> bool:
        return cache.get(cls._key(activation_code)) is not None

    @classmethod
    def get_status(cls, *, activation_code: str):
        return cache.get(cls._key(activation_code))

    # -------------------------------------------------
    # 🔽 NUEVO: helpers genéricos (NO rompen nada)
    # -------------------------------------------------

    @staticmethod
    def get_cache(key: str):
        """
        Obtiene un valor genérico desde Redis/Django cache
        """
        return cache.get(key)

    @staticmethod
    def set_cache(key: str, value, ttl_seconds: int):
        """
        Guarda un valor genérico en Redis/Django cache
        """
        cache.set(key, value, timeout=ttl_seconds)
