from django.core.cache import cache
from django.utils import timezone
from core.models import Device
from core.services.device_redis_service import DeviceRedisService



class DeviceService:
    LAST_SEEN_DB_EVERY_SECONDS = 300  # 5 min

    @staticmethod
    def _should_update_last_seen_db(activation_code: str) -> bool:
        """
        Devuelve True solo si ya pasó el throttle para escribir last_seen en DB.
        """
        key = f"device:last_seen_db:{activation_code}"
        return cache.add(key, "1", timeout=DeviceService.LAST_SEEN_DB_EVERY_SECONDS)

    @staticmethod
    def validate_device(*, activation_code: str, ip_address: str) -> Device:
        """
        Valida device, branch, IP y registra heartbeat.
        Es la ÚNICA función que toca Device.
        """
        try:
            device = Device.objects.select_related("branch").get(
                activation_code=activation_code
            )
        except Device.DoesNotExist:
            raise PermissionError("Invalid activation code")

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

        # ❤️ Heartbeat SIEMPRE a Redis (barato)
        DeviceRedisService.heartbeat(
            activation_code=device.activation_code,
            ip_address=ip_address,
            branch_id=device.branch_id,
        )

        # 🧠 last_seen en DB solo cada X minutos
        if DeviceService._should_update_last_seen_db(device.activation_code):
            device.last_seen = timezone.now()
            device.save(update_fields=["last_seen"])

        return device