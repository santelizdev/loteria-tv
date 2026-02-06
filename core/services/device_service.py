from core.models import Device
from core.services.device_redis_service import DeviceRedisService

class DeviceService:

    @staticmethod
    def validate_device(*, activation_code: str, ip_address: str) -> Device:
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


        DeviceRedisService.heartbeat(
            activation_code=device.activation_code,
            ip_address=ip_address,
            branch_id=device.branch_id,
        )

        return device
